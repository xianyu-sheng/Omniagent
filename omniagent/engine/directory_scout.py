"""
DirectoryScout — 目录侦察服务，为引擎规划阶段提供真实文件列表。

所有引擎（PlanExecute / PlanReact / ...）都可以通过此服务获取
目标项目的文件结构，避免 LLM 编造不存在的文件路径。

职责:
1. 从用户输入中提取目标目录路径
2. 执行 list_files 获取真实文件结构
3. 格式化为可注入 Plan prompt 的文本
4. 支持从对话历史回退提取（follow-up 消息）
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from omniagent.engine.context import AgentContext
from omniagent.engine.tool_tracker import ToolExecutionTracker

logger = logging.getLogger(__name__)

# ── Follow-up 消息检测 ──────────────────────────────────────

_FOLLOWUP_PATTERNS = [
    r"^(?:更|再|多).{0,5}(?:详细|具体|深入|丰富|完整)",
    r"^(?:不够|不太|还不|不).{0,5}(?:详细|具体|清楚|明确|好)",
    r"^(?:请|麻烦|再).{0,5}(?:展开|细化|补充|完善|说明|解释)",
    r"^(?:继续|接着说|然后呢|接下来|还有)",
    r"^(?:能|可以|可否|能否).{0,5}(?:更|再|多|补充|展开|深入)",
    r"^(?:above|more).{0,10}(?:detail|specific|elaborat)",
    r"^(?:elaborate|expand|detail|clarify)",
]


class ScoutResult:
    """侦察结果的结构化封装。"""

    def __init__(
        self,
        target_dir: str = "",
        root_files: str = "",
        py_files: str = "",
        total_chars: int = 0,
        is_from_history: bool = False,
        error: str | None = None,
    ) -> None:
        self.target_dir = target_dir
        self.root_files = root_files
        self.py_files = py_files
        self.total_chars = total_chars
        self.is_from_history = is_from_history
        self.error = error

    @property
    def has_data(self) -> bool:
        return bool(self.root_files or self.py_files)

    def to_plan_context(self) -> str:
        """格式化为可注入 Plan 提示词的文件列表文本。"""
        if not self.has_data:
            return ""
        parts = []
        if self.target_dir:
            parts.append(f"根目录文件 ({self.target_dir}):\n{self.root_files[:3000]}")
        if self.py_files:
            parts.append(f"所有 Python 文件 (递归):\n{self.py_files[:3000]}")
        return "\n\n".join(parts)

    def to_plan_input(self, user_input: str) -> str:
        """构建包含真实文件列表的 Plan 输入。"""
        if not self.has_data:
            return (
                f"{user_input}\n\n"
                "## 🔴 重要：当前消息中没有指定目录路径，且未获取到文件列表。\n"
                "如果你的任务需要访问本地文件，规划的**第一步必须是 list_files**。\n"
                "**绝对禁止**猜测不存在的文件名或目录名。\n"
                "如果你不需要访问文件（如纯对话/解释/展开已有分析），所有步骤的 tool 设为 null。"
            )
        context = self.to_plan_context()
        return (
            f"{user_input}\n\n"
            f"## 🔴 项目的真实文件列表（来自 list_files，请基于此规划）\n"
            f"```\n{context}\n```\n"
            f"请使用上述真实文件路径来规划 read_file 步骤。"
        )


class DirectoryScout:
    """目录侦察服务 — 为引擎提供项目文件结构。

    使用方式:
        scout = DirectoryScout()
        result = scout.scout(user_input, context, tracker)
        if result.has_data:
            plan_input = result.to_plan_input(user_input)
    """

    @staticmethod
    def extract_directory(text: str) -> str | None:
        """从用户输入中提取目标目录路径。"""
        # Windows 绝对路径: D:\xxx 或 C:\xxx
        m = re.search(r'([A-Za-z]:[\\/][^\s,，。；;]+)', text)
        if m:
            path = m.group(1).rstrip('\\/')
            return path
        # Unix 绝对路径: /home/xxx
        m = re.search(r'(/[^\s,，。；;]{2,})', text)
        if m:
            return m.group(1).rstrip('/')
        # 相对路径: ./xxx 或 ../xxx
        m = re.search(r'(\.\.?/[^\s,，。；;]+)', text)
        if m:
            return m.group(1).rstrip('/')
        return None

    def scout(
        self,
        user_input: str,
        context: AgentContext | None = None,
        tracker: ToolExecutionTracker | None = None,
    ) -> ScoutResult:
        """执行侦察：列出目标目录的文件结构。

        Args:
            user_input: 用户输入文本
            context: Agent 上下文（可选，用于获取对话历史）
            tracker: 工具跟踪器（可选）

        Returns:
            ScoutResult — 包含文件列表或错误信息
        """
        target_dir = self.extract_directory(user_input)
        if not target_dir:
            return ScoutResult()

        if not os.path.isdir(target_dir):
            return ScoutResult(target_dir=target_dir, error=f"目录不存在: {target_dir}")

        logger.info(f"DirectoryScout: 侦察目录 {target_dir}")

        try:
            from omniagent.engine.tool_executor import ToolExecutor
            ctx = context or AgentContext()
            executor = ToolExecutor()

            # 根目录列表
            root_result = executor.execute(
                "list_files",
                {"file_path": target_dir},
                ctx, tracker,
            )
            root_files = root_result.summary if root_result.success else ""

            # 递归列表（Python 文件）
            py_result = executor.execute(
                "list_files",
                {"file_path": target_dir, "pattern": "**/*.py"},
                ctx, tracker,
            )
            py_files = py_result.summary if py_result.success else ""

            total_chars = len(root_files) + len(py_files)
            logger.info(f"DirectoryScout: 完成 ({total_chars} chars)")

            return ScoutResult(
                target_dir=target_dir,
                root_files=root_files,
                py_files=py_files,
                total_chars=total_chars,
            )

        except Exception as e:
            logger.warning(f"DirectoryScout 失败: {e}")
            return ScoutResult(target_dir=target_dir, error=str(e))

    def scout_from_history(
        self,
        user_input: str,
        context: AgentContext | None = None,
        tracker: ToolExecutionTracker | None = None,
    ) -> ScoutResult | None:
        """从对话历史中回退提取目录（用于 follow-up 消息）。

        当当前消息没有目录路径时，从最近的对话历史中查找，
        为 follow-up 消息（如"更详细一些"）提供文件列表上下文。
        """
        if not self._is_followup(user_input):
            return None

        history = context.get_conversation_messages() if context else []
        for msg in reversed(history[-10:]):
            content = msg.get("content", "") if isinstance(msg, dict) else ""
            if not content:
                continue
            target_dir = self.extract_directory(content)
            if target_dir and os.path.isdir(target_dir):
                logger.info(f"DirectoryScout(fallback): 从对话历史提取目录 {target_dir}")
                result = self.scout(
                    f"分析 {target_dir}", context, tracker
                )
                if result.has_data:
                    result.is_from_history = True
                    return result
                break

        return None

    @staticmethod
    def _is_followup(text: str) -> bool:
        """检测用户输入是否是对话跟进（而非新任务）。"""
        for pattern in _FOLLOWUP_PATTERNS:
            if re.search(pattern, text, re.I):
                return True

        task_indicators = [
            r"(?:写|创建|生成|实现|开发|搭建|构建|做).{0,10}(?:一个|个|代码|函数|脚本|程序|项目|文件)",
            r"(?:create|write|build|implement|generate|make).{0,10}(?:a |an |code|function|script|project|file)",
            r"\b[A-Z]:[\\/]",
            r"\b\w+\.(?:py|js|ts|json|yaml|yml)\b",
        ]
        has_task = any(re.search(p, text, re.I) for p in task_indicators)
        if len(text) < 30 and not DirectoryScout.extract_directory(text) and not has_task:
            return True
        return False
