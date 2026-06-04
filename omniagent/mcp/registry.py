"""
MCP Registry — MCP 服务器注册和工具发现。

管理多个 MCP 服务器连接，统一工具命名空间。
"""

from __future__ import annotations

import logging
from typing import Any

from omniagent.mcp.client import MCPClient

logger = logging.getLogger(__name__)


class MCPRegistry:
    """MCP 服务器注册表。"""

    def __init__(self) -> None:
        # server_name -> MCPClient
        self.clients: dict[str, MCPClient] = {}
        # tool_name -> (server_name, tool_info)
        self.tool_map: dict[str, tuple[str, dict[str, Any]]] = {}

    def add_server(
        self,
        name: str,
        command: str | None = None,
        url: str | None = None,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> MCPClient:
        """添加 MCP 服务器。

        Args:
            name: 服务器名称（用于命名空间）
            command: stdio 模式的命令
            url: SSE 模式的 URL
            args: 命令参数
            env: 环境变量
        """
        if name in self.clients:
            logger.warning(f"MCP 服务器 '{name}' 已存在，跳过")
            return self.clients[name]

        if command:
            client = MCPClient.from_command(command, args, env, name=name)
        elif url:
            client = MCPClient.from_url(url, name=name)
        else:
            raise ValueError(f"MCP 服务器 '{name}' 需要 command 或 url")

        self.clients[name] = client
        logger.info(f"MCP 服务器已注册: {name}")
        return client

    def discover_tools(self) -> dict[str, list[dict[str, Any]]]:
        """发现所有服务器的工具。"""
        all_tools = {}
        for server_name, client in self.clients.items():
            try:
                tools = client.list_tools()
                all_tools[server_name] = tools
                for tool in tools:
                    tool_name = tool.get("name", "unknown")
                    # 使用 server:tool 作为全局名称
                    global_name = f"{server_name}:{tool_name}"
                    self.tool_map[global_name] = (server_name, tool)
                    # 也注册短名称（如果没有冲突）
                    if tool_name not in self.tool_map:
                        self.tool_map[tool_name] = (server_name, tool)
                logger.info(f"MCP 服务器 '{server_name}': 发现 {len(tools)} 个工具")
            except Exception as e:
                logger.warning(f"MCP 服务器 '{server_name}' 工具发现失败: {e}")

        return all_tools

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """调用 MCP 工具。支持 server:tool 或直接 tool 名称。"""
        entry = self.tool_map.get(tool_name)
        if not entry:
            # 尝试带 server 前缀
            for prefix in self.clients:
                full_name = f"{prefix}:{tool_name}"
                entry = self.tool_map.get(full_name)
                if entry:
                    break

        if not entry:
            available = list(self.tool_map.keys())
            raise ValueError(f"未知 MCP 工具: '{tool_name}'。可用: {available}")

        server_name, tool_info = entry
        client = self.clients[server_name]
        return client.call_tool(tool_info["name"], arguments)

    def format_all_tools_for_prompt(self) -> str:
        """将所有 MCP 工具格式化为 LLM 提示词。"""
        if not self.tool_map:
            self.discover_tools()

        lines = []
        for global_name, (server_name, tool) in sorted(self.tool_map.items()):
            if ":" not in global_name:
                continue  # 只显示带前缀的
            desc = tool.get("description", "")
            schema = tool.get("inputSchema", {})
            props = schema.get("properties", {})
            required = schema.get("required", [])

            params = []
            for pname, pinfo in props.items():
                req = "(必填)" if pname in required else ""
                params.append(f"{pname}: {pinfo.get('type', 'any')}{req}")

            params_str = ", ".join(params) if params else "无参数"
            lines.append(f"- {global_name}: {desc} (参数: {params_str})")

        return "\n".join(lines) if lines else "（无 MCP 工具）"

    def close_all(self) -> None:
        """关闭所有连接。"""
        for name, client in self.clients.items():
            try:
                client.close()
            except Exception as e:
                logger.warning(f"关闭 MCP 服务器 '{name}' 失败: {e}")
        self.clients.clear()
        self.tool_map.clear()

    @classmethod
    def from_config(cls, servers_config: list[dict[str, Any]]) -> MCPRegistry:
        """从配置创建注册表。

        配置格式:
        [
            {"name": "filesystem", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"]},
            {"name": "web", "url": "http://localhost:3000/sse"},
        ]
        """
        registry = cls()
        for server in servers_config:
            name = server.get("name", "unknown")
            try:
                registry.add_server(
                    name=name,
                    command=server.get("command"),
                    url=server.get("url"),
                    args=server.get("args"),
                    env=server.get("env"),
                )
            except Exception as e:
                logger.warning(f"添加 MCP 服务器 '{name}' 失败: {e}")
        return registry
