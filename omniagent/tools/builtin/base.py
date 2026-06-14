"""
BaseTool — 所有内置工具的抽象基类。

每个工具子类只需实现 execute() 方法，返回标准结果字典。
基类处理:
- 参数规范化（别名映射）
- 文件路径安全验证
- 模板变量替换
- 结果写入 context output_slot
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from omniagent.engine.context import AgentContext
from omniagent.engine.permissions import PermissionResult, get_permission_manager

logger = logging.getLogger(__name__)

# ── 安全常量 / 参数别名 — 从共享模块导入 ──
from omniagent.tools.security import (
    DANGEROUS_CMD_PATTERNS,
    DANGEROUS_GIT_PATTERNS,
    MAX_READ_SIZE,
    MAX_VERIFY_SIZE,
    MAX_WRITE_SIZE,
    PARAM_ALIASES,
    SENSITIVE_PATHS,
    USER_SENSITIVE,
)


class BaseTool:
    """所有工具的抽象基类。"""

    # 子类必须覆盖
    name: str = ""

    def __init__(
        self,
        *,
        security_enabled: bool = True,
        cwd: str | None = None,
        encoding: str = "utf-8",
        timeout: int = 60,
        output_slot: str | None = None,
        **kwargs,
    ) -> None:
        self.security_enabled = security_enabled
        self.cwd = cwd
        self.encoding = encoding
        self.timeout = timeout
        self.output_slot = output_slot
        self._extra = kwargs  # 捕获未知参数

    # ── 子类必须实现 ──

    def execute(self, context: AgentContext) -> dict[str, Any]:
        """执行工具操作，返回 {"success": bool, ...} 标准字典。"""
        raise NotImplementedError(f"{self.__class__.__name__}.execute()")

    # ── 工具方法 ──

    @classmethod
    def normalize_params(cls, params: dict) -> dict:
        """将 LLM 的别名参数映射为标准参数名。"""
        result = dict(params)
        for std_name, aliases in PARAM_ALIASES.items():
            if std_name in result:
                continue
            for alias in aliases:
                if alias in result:
                    result[std_name] = result.pop(alias)
                    break
        return result

    def resolve(self, template: str, context: AgentContext) -> str:
        """替换 {variable} 模板变量。"""
        def _replace(m: re.Match) -> str:
            val = context.get(m.group(1))
            return str(val) if val is not None else m.group(0)
        return re.sub(r"\{(\w+)\}", _replace, template)

    def _write_output(self, context: AgentContext, value: str) -> None:
        if self.output_slot:
            context.set(self.output_slot, value)

    # ── 安全验证 ──

    def _validate_path(self, file_path: str, *, for_write: bool = False) -> Path:
        """验证文件路径安全性。"""
        if not file_path:
            raise ValueError("文件路径不能为空")

        path = Path(file_path)
        if self.cwd and not path.is_absolute():
            path = Path(self.cwd) / path

        if not self.security_enabled:
            return path

        resolved = path.resolve()
        if for_write:
            try:
                resolved.relative_to(Path.cwd().resolve())
            except ValueError:
                raise PermissionError(f"写入路径越界: {resolved}")
        else:
            resolved_lower = str(resolved).lower().replace("\\", "/")
            for sensitive in SENSITIVE_PATHS:
                if sensitive in resolved_lower:
                    raise PermissionError(f"禁止读取系统敏感路径: {resolved}")

        if for_write:
            resolved_lower = str(resolved).lower().replace("\\", "/")
            for sensitive in SENSITIVE_PATHS:
                if sensitive in resolved_lower:
                    raise PermissionError(f"禁止写入系统敏感路径: {resolved}")
            for sensitive in USER_SENSITIVE:
                if sensitive in resolved.name.lower() or sensitive in resolved_lower:
                    raise PermissionError(f"禁止写入敏感文件: {resolved}")

        return path

    def _validate_command(self, cmd: str) -> None:
        if not self.security_enabled or not cmd:
            return
        cmd_lower = cmd.lower().strip()
        for pattern in DANGEROUS_CMD_PATTERNS:
            if re.search(pattern, cmd_lower):
                raise PermissionError(f"危险命令被拦截: {cmd[:100]}")

    def _validate_git_command(self, git_cmd: str) -> None:
        if not self.security_enabled:
            return
        cmd_lower = git_cmd.lower().strip()
        for dangerous in DANGEROUS_GIT_PATTERNS:
            if dangerous.lower() in cmd_lower:
                raise PermissionError(f"危险 Git 命令被拦截: git {git_cmd}")

    def _check_permission(self, tool_name: str, params: dict) -> PermissionResult:
        if not self.security_enabled:
            return PermissionResult("allow", "security disabled")
        return get_permission_manager().evaluate(tool_name, params)
