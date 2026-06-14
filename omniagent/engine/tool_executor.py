"""
统一工具执行器 — 所有引擎共享的单一工具执行入口。

职责:
1. 参数规范化与验证（拦截自然语言冒充路径参数）
2. 断路器保护（连续失败暂停）
3. 失败重试（可重试错误自动重试）
4. 终端错误检测（文件不存在等不重试）
5. 工具执行跟踪（ToolExecutionTracker 集成）

所有引擎（ReAct / PlanExecute / PlanReact 等）通过此服务统一调用工具。
"""

from __future__ import annotations

import logging
from typing import Any

from omniagent.engine.circuit_breaker import CircuitBreaker
from omniagent.engine.context import AgentContext
from omniagent.engine.tool_tracker import ToolExecutionTracker
from omniagent.nodes.tool_node import ToolNode

logger = logging.getLogger(__name__)

# 默认重试次数
DEFAULT_RETRY_ATTEMPTS = 2

# 信息获取类工具（成功后可提示合成）
INFO_TOOLS = {
    "weather", "datetime", "read_file", "list_files",
    "search_files", "web_fetch", "github_fetch",
}


class ToolExecuteResult:
    """工具执行结果的结构化封装。"""

    def __init__(
        self,
        tool_name: str,
        params: dict,
        success: bool,
        summary: str = "",
        error: str | None = None,
        *,
        is_terminal_error: bool = False,
        circuit_breaker_tripped: bool = False,
        attempts: int = 1,
    ) -> None:
        self.tool_name = tool_name
        self.params = params
        self.success = success
        self.summary = summary
        self.error = error
        self.is_terminal_error = is_terminal_error
        self.circuit_breaker_tripped = circuit_breaker_tripped
        self.attempts = attempts

    @property
    def is_info_tool(self) -> bool:
        return self.tool_name in INFO_TOOLS

    def next_hint(self) -> str:
        """根据执行结果生成下一步提示文本。"""
        if self.circuit_breaker_tripped:
            return "该工具暂时不可用（连续失败触发断路保护），请尝试其他工具或直接输出 final_answer。"
        if self.is_terminal_error:
            return "该资源/路径不存在，请勿重试。用已有信息继续或输出 final_answer。"
        if not self.success:
            if "缺少" in str(self.error or "") and "参数" in str(self.error or ""):
                return "请补充缺失的参数后重试，或跳过此工具用已有信息输出 final_answer。"
            return "分析失败原因，尝试其他方法或工具。如果无法解决，基于已有数据输出 final_answer。"
        if self.is_info_tool:
            return "信息已获取。如果你已收集足够数据，请直接输出 final_answer 交付结果。如还需要其他信息，继续调用工具。"
        return "操作完成。继续下一个操作或输出 final_answer。"

    def format_observation(self) -> str:
        """格式化为引擎观察消息。"""
        status_icon = "✅" if self.success else "❌"
        status_text = "执行完成" if self.success else "执行失败"
        summary_preview = self.summary[:3000] if self.summary else "(无输出)"
        error_text = f"\n错误: {self.error}" if self.error else ""

        return (
            f"📋 工具 '{self.tool_name}' 执行结果 ({status_icon} {status_text}):\n"
            f"{summary_preview}{error_text}\n\n"
            f"→ {self.next_hint()}"
        )


class ToolExecutor:
    """统一工具执行器 — 所有引擎共享的单一入口。

    使用方式:
        executor = ToolExecutor()
        result = executor.execute("read_file", {"file_path": "app.py"}, context, tracker)
    """

    def __init__(
        self,
        *,
        retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
        security_enabled: bool = True,
    ) -> None:
        self.retry_attempts = retry_attempts
        self.security_enabled = security_enabled
        self._breaker = CircuitBreaker()

    def execute(
        self,
        tool_name: str,
        params: dict,
        context: AgentContext,
        tracker: ToolExecutionTracker | None = None,
    ) -> ToolExecuteResult:
        """执行工具调用 — 包含完整的断路器+重试+验证流程。

        Args:
            tool_name: 工具名（如 "read_file", "write_file"）
            params: 原始参数字典（LLM 输出的格式）
            context: Agent 上下文
            tracker: 可选的工具跟踪器

        Returns:
            ToolExecuteResult — 结构化结果
        """
        # 1. 参数规范化
        normalized = ToolNode.normalize_params(params)

        # 2. 参数验证（只验证文件类工具）
        validated = _validate_tool_params(tool_name, normalized)
        if not validated["valid"]:
            error_msg = f"参数错误: {validated['reason']}"
            if tracker:
                tracker.record(tool_name, params, False, error_msg, error=error_msg)
            return ToolExecuteResult(tool_name, params, False, error=error_msg, is_terminal_error=True)

        params = normalized

        # 3. 断路器检查
        if not self._breaker.allow(tool_name):
            state = self._breaker.status(tool_name)
            cooldown_msg = (
                f"工具 '{tool_name}' 暂时不可用 — "
                f"连续失败 {state.get('consecutive_failures', 0)} 次, "
                f"冷却剩余 {state.get('cooldown_remaining', 0)} 秒"
            )
            if tracker:
                tracker.record(tool_name, params, False, cooldown_msg, error="circuit_breaker_cooldown")
            return ToolExecuteResult(
                tool_name, params, False, error=cooldown_msg,
                circuit_breaker_tripped=True,
            )

        # 4. 执行工具（含重试）
        for attempt in range(self.retry_attempts):
            try:
                node = ToolNode(
                    f"exec_{tool_name}",
                    action_type=tool_name,
                    security_enabled=self.security_enabled,
                    **params,
                )
                result = node.execute(context)
                success = result.get("success", False)
                error = result.get("error")

                if success:
                    # 提取摘要
                    summary = _extract_summary(result)
                    self._breaker.on_success(tool_name)
                    if tracker:
                        tracker.record(tool_name, params, True, summary[:200])
                    return ToolExecuteResult(
                        tool_name, params, True, summary=summary, attempts=attempt + 1,
                    )

                # 终端错误检测
                error_str = str(error) if error else str(result)
                if CircuitBreaker.is_terminal_error(tool_name, error_str):
                    terminal_msg = (
                        f"{tool_name} 失败（不可重试）: {error_str[:300]}"
                    )
                    self._breaker.on_failure(tool_name, error_str)
                    if tracker:
                        tracker.record(tool_name, params, False, terminal_msg, error=error_str)
                    return ToolExecuteResult(
                        tool_name, params, False, error=terminal_msg,
                        is_terminal_error=True,
                    )

                # 可重试错误
                self._breaker.on_failure(tool_name, error_str)
                if attempt < self.retry_attempts - 1:
                    logger.warning(f"工具 {tool_name} 失败，准备重试 ({attempt + 1}/{self.retry_attempts}): {error_str[:100]}")
                    continue

            except Exception as e:
                error_str = str(e)

                # 终端错误检测
                if CircuitBreaker.is_terminal_error(tool_name, error_str):
                    terminal_msg = f"{tool_name} 异常（不可重试）: {error_str[:300]}"
                    self._breaker.on_failure(tool_name, error_str)
                    if tracker:
                        tracker.record(tool_name, params, False, terminal_msg, error=error_str)
                    return ToolExecuteResult(
                        tool_name, params, False, error=terminal_msg,
                        is_terminal_error=True,
                    )

                self._breaker.on_failure(tool_name, error_str)
                if attempt < self.retry_attempts - 1:
                    logger.warning(f"工具 {tool_name} 异常，准备重试 ({attempt + 1}/{self.retry_attempts}): {e}")
                    continue

        # 所有重试耗尽
        error_msg = f"工具 '{tool_name}' 执行失败（{self.retry_attempts} 次尝试均失败）"
        # 检查断路器是否触发
        tripped_msg = self._breaker.on_failure_cooldown(tool_name, error_msg)
        if tripped_msg:
            error_msg = tripped_msg

        if tracker:
            tracker.record(tool_name, params, False, error_msg, error=error_msg)
        return ToolExecuteResult(tool_name, params, False, error=error_msg)


# ── 参数验证（从 plan_execute_engine 提取）───────────────────

_NL_PATH_PATTERNS = [
    r"基于步骤[一二三\d]+的(输出|结果)",
    r"根据.*步骤.*(输出|结果|文件)",
    r"来自.*(步骤|上一步|list_files).*(输出|结果)",
    r"从.*输出.*(获取|选择|读取)",
    r"上一?步.*(输出|结果|文件)",
    r"^\s*(步骤|根据|来自|基于|使用|参考|见|参见).*",
    r"[?？]",
    r"^(请|需要|应该|可以|必须|可能|尝试|确认)",
]

_PATH_TOOLS = {
    "read_file", "write_file", "edit_file", "list_files",
    "create_directory", "file_move", "file_copy",
    "ast_analyze", "refactor", "diff_preview",
}


def _validate_tool_params(tool: str, params: dict) -> dict:
    """验证工具参数，拦截将自然语言填入路径参数的情况。"""
    if not params:
        return {"valid": True, "reason": ""}

    if tool not in _PATH_TOOLS:
        return {"valid": True, "reason": ""}

    import re
    path_params = {"file_path", "path", "source", "destination"}
    for key in path_params & set(params.keys()):
        value = str(params[key]).strip()
        if not value:
            continue

        if len(value) > 200:
            return {
                "valid": False,
                "reason": f"参数 '{key}' 的值过长({len(value)}字符)，不像合法的文件路径: {value[:100]}...",
            }

        for pattern in _NL_PATH_PATTERNS:
            if re.search(pattern, value):
                return {
                    "valid": False,
                    "reason": f"参数 '{key}' 的值是自然语言描述而非实际路径: '{value[:80]}'. 请使用 list_files 输出的真实文件路径.",
                }

        cjk_count = sum(1 for c in value if '一' <= c <= '鿿')
        if cjk_count > 5 and not _looks_like_filesystem_path(value):
            return {
                "valid": False,
                "reason": (
                    f"参数 '{key}' 包含 {cjk_count} 个中文字符且没有路径结构特征: "
                    f"'{value[:80]}'. 这看起来是自然语言而非文件路径."
                ),
            }

    return {"valid": True, "reason": ""}


def _looks_like_filesystem_path(value: str) -> bool:
    """判断字符串是否像文件系统路径。"""
    import os, re
    if re.match(r'^[A-Za-z]:[\\/]', value):
        return True
    if value.startswith('/'):
        return True
    if value.startswith(('.\\', '..\\', './', '../')):
        return True
    if re.search(r'[\\/]', value) and re.search(r'\.\w{1,10}$', value):
        return True
    if os.path.exists(value):
        return True
    return False


# ── 摘要提取 ─────────────────────────────────────────────────

def _extract_summary(result: dict) -> str:
    """从 ToolNode 结果字典中提取主要文本摘要。"""
    for key in ("content", "stdout", "output", "files"):
        if result.get(key):
            val = result[key]
            if isinstance(val, list):
                return "\n".join(str(v) for v in val[:50])
            return str(val)[:3000]
    return str(result)[:3000]
