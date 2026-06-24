"""
Rich 卡片组件库 — OmniAgent CLI 的统一终端 UI 组件。

提供可复用的 Rich 卡片组件，实现类似 Aider / gptme 的终端 UI 风格：
- 信息视觉分层（dim 思考 → 彩色工具指示 → 高亮结果）
- 状态驱动的颜色编码（pending=yellow, running=cyan, success=green, error=red）
- 极简面板策略：仅 Error / Approval / 失败结果保留边框，其余用纯文本行

所有组件实现 ``__rich_console__`` 协议，可通过 ``console.print(Card(...))`` 直接渲染。
"""

from __future__ import annotations

from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

# ═══════════════════════════════════════════════════════════════════
# 统一工具图标映射
# ═══════════════════════════════════════════════════════════════════

TOOL_ICONS: dict[str, str] = {
    # 文件操作
    "read_file": "📖",
    "write_file": "📄",
    "edit_file": "✏️",
    "batch_write": "📝",
    "batch_edit": "📝",
    "list_files": "📋",
    "search_files": "🔍",
    "create_directory": "📁",
    "move_file": "📦",
    "copy_file": "📋",
    "delete_file": "🗑️",
    # 执行类
    "command": "⚡",
    "git": "🔀",
    # 网络/数据
    "web_fetch": "🌐",
    "github_fetch": "🐙",
    "weather": "🌤️",
    "datetime": "🕐",
    # Agent 相关
    "mcp_call": "🔌",
    "spawn_agent": "🤖",
    "agent_result": "📬",
    # 分析
    "code_index": "📊",
    "ast_analyze": "🔬",
    "refactor": "🔧",
    "diff_preview": "📊",
}

# 写入/敏感工具（始终显示，用强调色）
NOTIFY_TOOLS: set[str] = {
    "write_file", "edit_file", "batch_write", "batch_edit",
    "create_directory", "move_file", "copy_file", "delete_file",
    "command", "git", "mcp_call", "spawn_agent",
}

# 信息获取工具（低调显示）
INFO_TOOLS: set[str] = {
    "read_file", "list_files", "search_files",
    "web_fetch", "github_fetch", "weather", "datetime",
}

# 向后兼容别名
_NOTIFY_TOOLS = NOTIFY_TOOLS
_INFO_TOOLS = INFO_TOOLS


def _is_notify_tool(tool_name: str) -> bool:
    return tool_name in NOTIFY_TOOLS


def _status_color(status: str) -> str:
    return {
        "pending": "yellow",
        "running": "bright_cyan",
        "success": "green",
        "error": "red",
        "denied": "red",
        "info": "dim",
    }.get(status, "dim")


def _truncate(text: str, max_len: int = 80) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


# ═══════════════════════════════════════════════════════════════════
# 卡片组件
# ═══════════════════════════════════════════════════════════════════


class ToolCallCard:
    """工具调用指示 — 纯文本行，无边框。

    视觉设计（极简）：
    - 写入/命令工具: 彩色图标 + 工具名，dim 参数
    - 读取/搜索工具: 全 dim 单行

    Usage::

        card = ToolCallCard("write_file", {"file_path": "a.py", "content": "..."})
        console.print(card)
    """

    def __init__(
        self,
        tool_name: str,
        params: dict,
        *,
        status: str = "running",
        compact: bool | None = None,
    ) -> None:
        self.tool_name = tool_name
        self.params = params
        self.status = status
        if compact is None:
            compact = not _is_notify_tool(tool_name)
        self.compact = compact

    def __rich_console__(self, console, options):
        icon = TOOL_ICONS.get(self.tool_name, "🔧")
        params_brief = _format_params_brief(self.tool_name, self.params)

        if self.compact:
            # 信息工具：全 dim
            line = f"  [dim]{icon} {self.tool_name}[/dim]"
            if params_brief:
                line += f" [dim]{params_brief}[/dim]"
            yield Text.from_markup(line)
        else:
            # 写入/敏感工具：彩色强调图标+工具名，dim 参数
            color = "bright_cyan"
            line = f"  [bold {color}]{icon} {self.tool_name}[/bold {color}]"
            if params_brief:
                line += f" [dim]{params_brief}[/dim]"
            yield Text.from_markup(line)


class ToolResultCard:
    """工具执行结果 — 成功用纯文本行，失败/拒绝/断路用紧凑 Panel。

    视觉设计：
    - 成功: 绿色文本行，无边框
    - 权限拒绝/断路器/失败: 红色紧凑 Panel（需要用户注意）
    """

    def __init__(
        self,
        tool_name: str,
        success: bool,
        summary: str,
        *,
        error: str | None = None,
        permission_denied: bool = False,
        circuit_breaker_tripped: bool = False,
    ) -> None:
        self.tool_name = tool_name
        self.success = success
        self.summary = summary
        self.error = error
        self.permission_denied = permission_denied
        self.circuit_breaker_tripped = circuit_breaker_tripped

    def __rich_console__(self, console, options):
        icon = TOOL_ICONS.get(self.tool_name, "🔧")
        tool_display = f"{icon} {self.tool_name}".strip()

        if self.permission_denied:
            yield Panel(
                Text.from_markup(
                    f"[bold red]⛔ 已拒绝 {tool_display}[/bold red]\n"
                    f"[dim red]{_truncate(self.summary, 200)}[/dim red]"
                ),
                border_style="red",
                padding=(0, 1),
            )
            return

        if self.circuit_breaker_tripped:
            yield Panel(
                Text.from_markup(
                    f"[bold red]🛑 断路器触发 {tool_display}[/bold red]\n"
                    f"[dim red]{_truncate(self.summary, 200)}[/dim red]"
                ),
                border_style="red",
                padding=(0, 1),
            )
            return

        if self.success:
            # 成功 → 纯文本行，无边框
            line = f"  [green]✅[/green]"
            if tool_display:
                line += f" [green]{tool_display}[/green]"
            if self.summary:
                line += f" [dim green]{_truncate(self.summary, 200)}[/dim green]"
            yield Text.from_markup(line)
            return

        # 失败 → 紧凑 Panel
        err_text = self.error or self.summary or ""
        yield Panel(
            Text.from_markup(
                f"[bold red]❌ {tool_display} 失败[/bold red]\n"
                f"[dim red]{_truncate(err_text, 300)}[/dim red]"
            ),
            border_style="red",
            padding=(0, 1),
        )


class ThinkingCard:
    """LLM 思考内容 — 纯 dim 文本，无边框，最低视觉权重。"""

    def __init__(
        self,
        thought: str,
        *,
        step_number: int | None = None,
        compact: bool = False,
    ) -> None:
        self.thought = thought
        self.step_number = step_number
        self.compact = compact

    def __rich_console__(self, console, options):
        prefix = (
            f"[dim]🤔[/dim]"
            if self.step_number is None
            else f"[dim]#{self.step_number} 🤔[/dim]"
        )
        thought_short = _truncate(self.thought.replace("\n", " "), 150)
        yield Text.from_markup(
            f"  {prefix} [dim italic]{thought_short}[/dim italic]"
        )


class StepCard:
    """Plan-Execute 步骤指示 — 纯文本行，无边框。

    用颜色 + 图标区分 running / done / failed。
    """

    def __init__(
        self,
        step_id: int,
        total: int,
        task: str,
        *,
        status: str = "pending",
    ) -> None:
        self.step_id = step_id
        self.total = total
        self.task = task
        self.status = status

    def __rich_console__(self, console, options):
        color = _status_color(self.status)
        if self.status == "running":
            icon = "▸"
        elif self.status == "done":
            icon = "✅"
        elif self.status == "failed":
            icon = "❌"
        else:
            icon = "○"

        task_display = _truncate(self.task, 120)
        yield Text.from_markup(
            f"  [{color}]{icon}[/{color}] "
            f"[dim]步骤[/dim] [bold]{self.step_id}/{self.total}[/bold] "
            f"[dim]{task_display}[/dim]"
        )


class ErrorCard:
    """错误/警告卡片 — 保留紧凑 Panel，必须引起用户注意。"""

    def __init__(
        self,
        message: str,
        *,
        title: str = "错误",
        details: str | None = None,
        is_warning: bool = False,
    ) -> None:
        self.message = message
        self.title = title
        self.details = details
        self.is_warning = is_warning

    def __rich_console__(self, console, options):
        color = "yellow" if self.is_warning else "red"
        icon = "⚠️" if self.is_warning else "❌"

        content = f"[bold {color}]{icon} {self.title}[/bold {color}]\n"
        content += f"[{color}]{_truncate(self.message, 300)}[/{color}]"
        if self.details:
            content += f"\n[dim {color}]{_truncate(self.details, 500)}[/dim {color}]"

        yield Panel(
            Text.from_markup(content),
            border_style=color,
            padding=(0, 1),
        )


class ApprovalCard:
    """权限审批对话框 — 保留边框，关键交互节点。"""

    def __init__(
        self,
        tool_name: str,
        params_preview: str,
        *,
        always_approved_count: int = 0,
    ) -> None:
        self.tool_name = tool_name
        self.params_preview = params_preview
        self.always_approved_count = always_approved_count

    def __rich_console__(self, console, options):
        icon = TOOL_ICONS.get(self.tool_name, "🔧")

        if self.tool_name in ("write_file", "edit_file", "batch_write", "batch_edit"):
            action_desc = "OmniAgent 需要写入文件"
        elif self.tool_name == "command":
            action_desc = "OmniAgent 需要执行命令"
        elif self.tool_name == "git":
            action_desc = "OmniAgent 需要执行 Git 操作"
        elif self.tool_name in ("create_directory", "move_file", "copy_file", "delete_file"):
            action_desc = "OmniAgent 需要操作文件系统"
        elif self.tool_name == "mcp_call":
            action_desc = "OmniAgent 需要调用外部 MCP 工具"
        elif self.tool_name == "spawn_agent":
            action_desc = "OmniAgent 需要启动子 Agent"
        else:
            action_desc = f"OmniAgent 需要调用工具 {icon} {self.tool_name}"

        content = f"[bold bright_cyan]{icon} {action_desc}[/bold bright_cyan]\n\n"
        content += f"[dim]{_truncate(self.params_preview, 250)}[/dim]\n\n"
        content += "[dim]▸ 选择: [/dim]"
        content += "[bold green](y) 批准一次[/bold green]  "
        content += "[bold cyan](a) 始终批准[/bold cyan]  "
        content += "[bold red](n) 拒绝[/bold red]"

        if self.always_approved_count > 0:
            content += f"\n[dim cyan]📌 当前会话已授权 {self.always_approved_count} 项[/dim cyan]"

        yield Panel(
            Text.from_markup(content),
            title="[bold bright_cyan]◆ 权限审批[/bold bright_cyan]",
            border_style="bright_cyan",
            padding=(1, 2),
        )


class ModeHeader:
    """引擎模式头部 — 简洁分隔线 + 关键信息，无面板边框。"""

    def __init__(
        self,
        mode: str,
        *,
        description: str = "",
        iterations: int | None = None,
        extra_info: str = "",
    ) -> None:
        self.mode = mode
        self.description = description
        self.iterations = iterations
        self.extra_info = extra_info

    def __rich_console__(self, console, options):
        parts: list[str] = []

        if self.mode == "ReAct":
            parts.append("[bold bright_cyan]🔄 ReAct[/bold bright_cyan]")
            parts.append("[dim]思考 → 行动 → 观察[/dim]")
        elif self.mode == "Plan-Execute":
            parts.append("[bold bright_cyan]📋 Plan-Execute[/bold bright_cyan]")
            parts.append("[dim]规划 → 逐步执行[/dim]")
        elif self.mode == "Reflection":
            parts.append("[bold bright_cyan]🔍 Reflection[/bold bright_cyan]")
            parts.append("[dim]执行 → 审查 → 修正[/dim]")
        elif self.mode == "Direct":
            parts.append("[bold bright_cyan]💬 Direct[/bold bright_cyan]")
            parts.append("[dim]直接对话[/dim]")
        elif self.mode == "Plan+React":
            parts.append("[bold bright_cyan]📋🔄 Plan+React[/bold bright_cyan]")
            parts.append("[dim]全局规划 → ReAct 执行[/dim]")
        elif self.mode == "Plan+Reflection":
            parts.append("[bold bright_cyan]📋🔍 Plan+Reflection[/bold bright_cyan]")
            parts.append("[dim]规划执行 → 反思修正[/dim]")
        elif self.mode == "React+Reflection":
            parts.append("[bold bright_cyan]🔄🔍 React+Reflection[/bold bright_cyan]")
            parts.append("[dim]ReAct 探索 → 反思审查[/dim]")
        elif self.mode == "Novel":
            parts.append("[bold magenta]📖 Novel[/bold magenta]")
            parts.append("[dim]小说创作助手[/dim]")
        else:
            parts.append(f"[bold bright_cyan]📐 {self.mode}[/bold bright_cyan]")
            if self.description:
                parts.append(f"[dim]{self.description}[/dim]")

        if self.iterations is not None:
            parts.append(f"[dim]· {self.iterations} 轮[/dim]")
        if self.extra_info:
            parts.append(f"[dim]· {self.extra_info}[/dim]")

        yield Rule(
            "  ".join(parts),
            style="dim",
            align="left",
        )


# ═══════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════


def _format_params_brief(tool_name: str, params: dict) -> str:
    """生成一行参数预览。"""
    if tool_name == "command":
        return _truncate(str(params.get("command", "")), 100)
    if tool_name == "git":
        git_cmd = params.get("git_command") or params.get("command", "")
        return _truncate(str(git_cmd), 80)
    if tool_name in ("write_file", "edit_file", "read_file"):
        return _truncate(str(params.get("file_path", "")), 80)
    if tool_name in ("list_files", "create_directory"):
        path = params.get("file_path") or params.get("path", "")
        return _truncate(str(path), 60)
    if tool_name == "search_files":
        pattern = params.get("search_pattern") or params.get("pattern", "")
        return _truncate(str(pattern), 60)
    if tool_name in ("web_fetch", "github_fetch"):
        return _truncate(str(params.get("url", "")), 80)
    for key in ("file_path", "path", "url", "query", "search_pattern"):
        if key in params:
            return _truncate(str(params[key]), 60)
    return ""


def render_shortcut_bar() -> Text:
    """渲染底部快捷键提示 — 纯 dim 文本，无边框。"""
    return Text.from_markup(
        "[dim]"
        "Ctrl+C 退出 · Esc 中断 · /help 命令 · "
        "/mode 切换范式 · /model 切换模型 · "
        "/compact 压缩上下文"
        "[/dim]"
    )
