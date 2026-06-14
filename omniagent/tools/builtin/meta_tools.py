"""
Meta tools — mcp_call, register_tool, datetime, dynamic tool execution
"""

from __future__ import annotations

import importlib
import json
import logging
import subprocess
from datetime import datetime
from typing import Any

from omniagent.engine.context import AgentContext
from omniagent.tools.builtin.base import BaseTool

logger = logging.getLogger(__name__)

# ── 动态工具注册表（从 ToolNode 迁移）──
_DYNAMIC_TOOLS: dict[str, dict] = {}


def register_dynamic_tool(name: str, handler, description: str, params: dict) -> None:
    _DYNAMIC_TOOLS[name] = {"handler": handler, "description": description, "params": params}


def get_dynamic_tool_schema(name: str) -> dict | None:
    info = _DYNAMIC_TOOLS.get(name)
    return {"name": name, "description": info["description"], "params": info["params"]} if info else None


def list_dynamic_tools() -> list[str]:
    return list(_DYNAMIC_TOOLS.keys())


class MCPCallTool(BaseTool):
    name = "mcp_call"

    def execute(self, context: AgentContext) -> dict[str, Any]:
        tool_name = self.resolve(self._extra.get("tool_name", ""), context)
        if not tool_name:
            return {"action_type": "mcp_call", "success": False, "error": "需要 tool_name 参数"}

        registry = context.get("_mcp_registry")
        if not registry:
            return {"action_type": "mcp_call", "success": False, "error": "MCP 未初始化，请先使用 /mcp add 添加服务器"}

        try:
            args = {k: self.resolve(v, context) if isinstance(v, str) else v for k, v in self._extra.get("tool_args", {}).items()}
            result = registry.call_tool(tool_name, args)
            content_parts = [item.get("text", str(item)) for item in result.get("content", []) if item.get("type") == "text" or "text" in item]
            display = "\n".join(content_parts) if content_parts else str(result)
            self._write_output(context, display[:5000])
            return {"action_type": "mcp_call", "tool": tool_name, "result": result, "success": True}
        except Exception as e:
            return {"action_type": "mcp_call", "tool": tool_name, "success": False, "error": str(e)}


class RegisterToolTool(BaseTool):
    name = "register_tool"

    def execute(self, context: AgentContext) -> dict[str, Any]:
        tool_name = self.resolve(self._extra.get("tool_name", ""), context)
        description = self.resolve(self._extra.get("description", ""), context)
        params_raw = self._extra.get("params", {})
        if isinstance(params_raw, str):
            try:
                params_raw = json.loads(params_raw)
            except json.JSONDecodeError:
                params_raw = {}

        if not tool_name:
            return {"action_type": "register_tool", "success": False, "error": "需要 tool_name"}

        python_function = self.resolve(self._extra.get("python_function", ""), context)
        if python_function:
            try:
                parts = python_function.rsplit(".", 1)
                if len(parts) != 2:
                    return {"action_type": "register_tool", "success": False, "error": f"python_function 格式错误: {python_function}"}
                mod = importlib.import_module(parts[0])
                func = getattr(mod, parts[1])
                if not callable(func):
                    return {"action_type": "register_tool", "success": False, "error": f"{python_function} 不可调用"}

                def make_handler(fn):
                    def handler(ctx):
                        kwargs = {key: ctx.get(key) for key in (params_raw.get("properties") or {}) if ctx.get(key) is not None}
                        try:
                            result = fn(**kwargs) if kwargs else fn()
                            return {"action_type": tool_name, "success": True, "content": str(result)}
                        except Exception as e:
                            return {"action_type": tool_name, "success": False, "error": str(e)}
                    return handler

                register_dynamic_tool(tool_name, make_handler(func), description or f"自定义: {tool_name}", params_raw)
                return {"action_type": "register_tool", "success": True, "content": f"工具 '{tool_name}' 注册成功 (Python: {python_function})"}
            except Exception as e:
                return {"action_type": "register_tool", "success": False, "error": f"注册失败: {e}"}

        command_template = self.resolve(self._extra.get("command_template", ""), context)
        if command_template:
            def cmd_handler(ctx):
                cmd = command_template
                for key in (params_raw.get("properties") or {}):
                    val = ctx.get(key)
                    if val is not None:
                        cmd = cmd.replace(f"{{{key}}}", str(val))
                try:
                    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                    return {"action_type": tool_name, "success": result.returncode == 0, "content": result.stdout.strip(), "command": cmd}
                except subprocess.TimeoutExpired:
                    return {"action_type": tool_name, "success": False, "error": "命令超时 (30s)"}
                except Exception as e:
                    return {"action_type": tool_name, "success": False, "error": str(e)}

            register_dynamic_tool(tool_name, cmd_handler, description or f"自定义命令: {tool_name}", params_raw)
            return {"action_type": "register_tool", "success": True, "content": f"工具 '{tool_name}' 注册成功 (命令模板)"}

        return {"action_type": "register_tool", "success": False, "error": "需要 python_function 或 command_template"}


class DateTimeTool(BaseTool):
    name = "datetime"

    def execute(self, context: AgentContext) -> dict[str, Any]:
        now = datetime.now()
        weekdays_cn = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

        date_str = f"{now.year}年{now.month}月{now.day}日"
        time_str = now.strftime("%H:%M:%S")
        weekday = weekdays_cn[now.weekday()]

        content = f"当前日期: {date_str} {weekday}\n当前时间: {time_str}"
        result = {
            "action_type": "datetime", "success": True, "content": content,
            "date": date_str, "time": time_str, "weekday": weekday,
            "year": now.year, "month": now.month, "day": now.day,
        }
        self._write_output(context, content)
        return result
