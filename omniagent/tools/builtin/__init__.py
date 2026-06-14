"""
Builtin tools — 独立工具类集合。

每个工具类继承 BaseTool，通过 ToolRegistry 注册。
ToolNode 变为薄调度层，通过注册表查找并委托执行。
"""

from omniagent.tools.builtin.base import BaseTool
from omniagent.tools.builtin.file_tools import (
    ReadFileTool, WriteFileTool, EditFileTool, ListFilesTool,
    SearchFilesTool, CreateDirectoryTool, MoveFileTool, CopyFileTool,
)
from omniagent.tools.builtin.exec_tools import CommandTool, GitTool
from omniagent.tools.builtin.web_tools import WebFetchTool, GitHubFetchTool, WeatherTool
from omniagent.tools.builtin.code_tools import (
    CodeIndexTool, AstAnalyzeTool, RefactorTool, DiffPreviewTool,
)
from omniagent.tools.builtin.batch_tools import BatchWriteTool, BatchEditTool
from omniagent.tools.builtin.meta_tools import MCPCallTool, RegisterToolTool, DateTimeTool
from omniagent.tools.builtin.subagent_tools import SpawnAgentTool, AgentResultTool

__all__ = [
    "BaseTool",
    "ReadFileTool", "WriteFileTool", "EditFileTool", "ListFilesTool",
    "SearchFilesTool", "CreateDirectoryTool", "MoveFileTool", "CopyFileTool",
    "CommandTool", "GitTool",
    "WebFetchTool", "GitHubFetchTool", "WeatherTool",
    "CodeIndexTool", "AstAnalyzeTool", "RefactorTool", "DiffPreviewTool",
    "BatchWriteTool", "BatchEditTool",
    "MCPCallTool", "RegisterToolTool", "DateTimeTool",
    "SpawnAgentTool", "AgentResultTool",
]
