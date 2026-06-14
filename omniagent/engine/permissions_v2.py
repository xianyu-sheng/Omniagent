"""增强权限管理器 — 借鉴 KamaClaude 的 6 层评估 + 交互式审批。

⚠️ DEPRECATED — 当前仅由测试文件 (test_kamaclaude_integration.py) 使用。
   生产代码使用 permissions.py 中的简化版 ToolPolicy。
   此模块依赖异步 EventBus (events/bus.py)，仅在 daemon/TUI 路径中可用。
   待异步路径统一后，此模块将取代 permissions.py 成为唯一的权限系统。

层级:
  Tier 1: deny_patterns（硬拒绝，不可被缓存绕过）
  Tier 2: OUTSIDE_CWD（强制 ask，不可被缓存绕过）
  Tier 3: session always 缓存
  Tier 4: persistent always（跨 session 持久化）
  Tier 5: allow_patterns（自动放行）
  Tier 6: tool default（allow/deny/ask）

对于需要 ask 的情况，通过 EventBus 发布 PermissionRequestEvent 等待客户端响应。
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolPolicy:
    """单个工具的权限策略。"""
    default: str = "allow"  # allow | deny | ask
    allow_patterns: list[str] = field(default_factory=list)
    deny_patterns: list[str] = field(default_factory=list)


# ── 默认策略 ────────────────────────────────────────────────

DEFAULT_POLICIES: dict[str, ToolPolicy] = {
    "command": ToolPolicy(
        default="allow",
        deny_patterns=[
            r"rm\s+(-[rfR]+\s+)?/", r"del\s+/[sfq]\s+C:\\",
            r"\bformat\s+[a-zA-Z]:", r"\bshutdown\b", r"\breboot\b",
            r"curl.*\|\s*(?:bash|sh|python|node)",
            r"Remove-Item\s+-[rR].*C:\\",
            r"\bchmod\s+777\b",
        ],
    ),
    "git": ToolPolicy(
        default="allow",
        deny_patterns=[
            r"push\s+--force", r"push\s+-f", r"reset\s+--hard",
            r"clean\s+-fd", r"checkout\s+--\s+\.",
        ],
    ),
    "write_file": ToolPolicy(default="allow"),
    "edit_file": ToolPolicy(default="allow"),
    "batch_write": ToolPolicy(default="allow"),
    "batch_edit": ToolPolicy(default="allow"),
    "create_directory": ToolPolicy(default="allow"),
    "mcp_call": ToolPolicy(default="ask"),  # MCP 默认需要审批
}

_OUTSIDE_CWD_PATTERNS = [
    r"(?:^|\s)(?:/[a-zA-Z]+)+",           # 绝对 Unix 路径
    r"(?:^|\s)[A-Z]:[\\/]",                # 绝对 Windows 路径
    r"\bcp\s+.*\s+(?:/[a-zA-Z]+|[A-Z]:)",
    r"\bmv\s+.*\s+(?:/[a-zA-Z]+|[A-Z]:)",
]


def matches_outside_cwd(command: str) -> bool:
    """检查命令是否可能访问项目目录外的路径。"""
    for pattern in _OUTSIDE_CWD_PATTERNS:
        if re.search(pattern, command):
            return True
    return False


# ── 权限管理器 ──────────────────────────────────────────────

@dataclass
class _PendingRequest:
    """等待审批的权限请求。"""
    future: asyncio.Future[str]
    tool_name: str
    params_preview: str


class PermissionManagerV2:
    """增强版权限管理器 — 6 层评估 + 交互式审批。"""

    def __init__(
        self,
        policies: dict[str, ToolPolicy] | None = None,
        *,
        policy_path: Path | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        self._policies = policies or dict(DEFAULT_POLICIES)
        self._policy_path = policy_path or Path(".omniagent/policy.yaml")
        self._timeout_s = timeout_s

        # 缓存
        self._session_always: dict[tuple[str, str], str] = {}  # (session_id, tool_name) → allow|deny
        self._persistent_always: dict[str, str] = {}  # tool_name → allow|deny

        # 待审批请求
        self._pending: dict[str, _PendingRequest] = {}

        # 事件发射器（用于交互式审批）
        self._event_emitter: Callable[..., Coroutine] | None = None

        self._load_policy_file()

    def set_event_emitter(self, emitter: Callable[..., Coroutine]) -> None:
        """设置事件发射器（用于向客户端推送审批请求）。"""
        self._event_emitter = emitter

    # ── 策略评估 ────────────────────────────────────────────

    def evaluate(
        self, tool_name: str, params: dict[str, Any],
        session_id: str = "",
    ) -> tuple[str, str]:
        """评估工具调用权限。返回 (decision, reason)。

        decision: "allow" | "deny" | "ask"
        """
        command = str(params.get("command", "") or params.get("action", ""))
        policy = self._policies.get(tool_name)

        # Tier 1: deny_patterns（硬拒绝，优先级最高）
        if command and policy:
            for pat in policy.deny_patterns:
                if re.search(pat, command, re.IGNORECASE):
                    return "deny", f"匹配拒绝模式: {pat}"

        # Tier 2: OUTSIDE_CWD（强制 ask）
        if command and matches_outside_cwd(command):
            return "ask", "命令可能访问项目目录外路径"

        # Tier 3: session always 缓存
        if session_id:
            key = (session_id, tool_name)
            if key in self._session_always:
                return self._session_always[key], "session 缓存"

        # Tier 4: persistent always
        if tool_name in self._persistent_always:
            return self._persistent_always[tool_name], "持久化缓存"

        # Tier 5: allow_patterns
        if command and policy:
            for pat in policy.allow_patterns:
                if re.search(pat, command, re.IGNORECASE):
                    return "allow", f"匹配放行模式: {pat}"

        # Tier 6: default
        if policy:
            return policy.default, "默认策略"
        return "allow", "无策略（默认放行）"

    # ── 交互式审批 ──────────────────────────────────────────

    async def check_and_wait(
        self,
        tool_use_id: str,
        tool_name: str,
        params: dict[str, Any],
        session_id: str,
    ) -> tuple[bool, str]:
        """检查权限，如果需要审批则等待客户端响应。

        Returns:
            (allowed: bool, decision: str)
        """
        decision, reason = self.evaluate(tool_name, params, session_id)

        if decision == "deny":
            return False, f"auto_deny: {reason}"
        if decision == "allow":
            return True, f"auto_allow: {reason}"

        # decision == "ask": 需要等待审批
        if not self._event_emitter:
            # 没有事件发射器，拒绝（安全优先）
            return False, "permission_denied: no event emitter for interactive approval"

        params_preview = self._params_summary(tool_name, params)
        future: asyncio.Future[str] = asyncio.Future()
        self._pending[tool_use_id] = _PendingRequest(
            future=future, tool_name=tool_name, params_preview=params_preview,
        )

        # 发射审批事件
        if self._event_emitter:
            try:
                await self._event_emitter({
                    "type": "event.permission.request",
                    "data": {
                        "tool_use_id": tool_use_id,
                        "tool_name": tool_name,
                        "params_preview": params_preview,
                        "session_id": session_id,
                    },
                })
            except Exception as e:
                logger.warning(f"发射权限事件失败: {e}")

        try:
            result = await asyncio.wait_for(future, timeout=self._timeout_s)
        except asyncio.TimeoutError:
            self._pending.pop(tool_use_id, None)
            return False, "permission_timeout"

        return result == "allow" or result == "always_allow", result

    def respond(self, tool_use_id: str, decision: str) -> bool:
        """客户端响应审批请求。

        Args:
            tool_use_id: 工具调用 ID
            decision: "allow_once" | "always_allow" | "deny_once" | "always_deny"

        Returns:
            是否找到对应的待审批请求
        """
        pending = self._pending.pop(tool_use_id, None)
        if pending is None:
            return False

        result = "allow" if decision.startswith("allow") else "deny"
        pending.future.set_result(decision)
        return True

    def set_session_allow(self, session_id: str, tool_name: str, allow: bool) -> None:
        """设置 session 级 always 缓存。"""
        self._session_always[(session_id, tool_name)] = "allow" if allow else "deny"

    def set_persistent_allow(self, tool_name: str, allow: bool) -> None:
        """设置持久化 always 缓存。"""
        self._persistent_always[tool_name] = "allow" if allow else "deny"
        self._save_policy_file()

    # ── 工具 ────────────────────────────────────────────────

    @staticmethod
    def _params_summary(tool_name: str, params: dict[str, Any]) -> str:
        """生成参数摘要（用于审批展示）。"""
        keys_by_tool = {
            "command": ("action", "command"),
            "write_file": ("file_path",),
            "read_file": ("file_path",),
            "edit_file": ("file_path",),
            "create_directory": ("file_path",),
            "git": ("git_command",),
        }
        keys = keys_by_tool.get(tool_name, ())
        parts = [f"{k}={params[k]!r}" for k in keys if k in params]
        if not parts:
            parts = [f"{k}={v!r}" for k, v in list(params.items())[:2]]
        return ", ".join(parts)

    def _load_policy_file(self) -> None:
        """从 .omniagent/policy.yaml 加载持久化策略。"""
        if not self._policy_path.exists():
            return
        try:
            import yaml
            data = yaml.safe_load(self._policy_path.read_text(encoding="utf-8")) or {}
            always = data.get("always", {})
            if isinstance(always, dict):
                for name, decision in always.items():
                    if decision in ("allow", "deny"):
                        self._persistent_always[str(name)] = str(decision)
        except Exception as e:
            logger.debug(f"加载策略文件失败: {e}")

    def _save_policy_file(self) -> None:
        """保存持久化策略到文件。"""
        try:
            self._policy_path.parent.mkdir(parents=True, exist_ok=True)
            import yaml
            self._policy_path.write_text(
                yaml.dump({"always": self._persistent_always}, allow_unicode=True),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"保存策略文件失败: {e}")
