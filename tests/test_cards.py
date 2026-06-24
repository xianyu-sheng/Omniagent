"""
Card component tests — 验证所有 Rich 卡片组件正确渲染（极简面板策略）。
"""
from __future__ import annotations

import pytest
from rich.console import Console
from rich.text import Text as RichText

from omniagent.repl.cards import (
    TOOL_ICONS,
    ApprovalCard,
    ErrorCard,
    ModeHeader,
    StepCard,
    ThinkingCard,
    ToolCallCard,
    ToolResultCard,
    render_shortcut_bar,
)


def _render_text(renderable) -> str:
    """Helper: render any Rich-renderable to plain text string."""
    console = Console(width=120, color_system="standard")
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


class TestToolCallCard:
    """ToolCallCard tests — 纯文本行，无边框。"""

    def test_write_tool_shows_colored(self):
        """写入工具：彩色强调图标+工具名 + dim 参数"""
        card = ToolCallCard("write_file", {"file_path": "a.py", "content": "x"})
        text = _render_text(card)
        assert "write_file" in text
        assert "a.py" in text

    def test_read_tool_dim(self):
        """读取工具：全 dim 单行"""
        card = ToolCallCard("read_file", {"file_path": "readme.md"})
        text = _render_text(card)
        assert "read_file" in text
        assert "readme.md" in text

    def test_unknown_tool_icon_fallback(self):
        card = ToolCallCard("unknown_tool", {})
        text = _render_text(card)
        assert "unknown_tool" in text
        assert "🔧" in text

    def test_notify_tool_always_visible(self):
        """写入/命令类工具始终显示"""
        card = ToolCallCard("command", {"command": "pytest tests -q"})
        text = _render_text(card)
        assert "command" in text
        assert "pytest" in text

    def test_compact_explicit(self):
        """显式 compact 时使用全 dim"""
        card = ToolCallCard("write_file", {"file_path": "a.py"}, compact=True)
        text = _render_text(card)
        assert "write_file" in text
        assert "a.py" in text


class TestToolResultCard:
    """ToolResultCard tests — 成功用纯文本，失败/拒绝用紧凑 Panel。"""

    def test_success_is_text_line(self):
        """成功 → 纯文本行，无 Panel 边框"""
        card = ToolResultCard("write_file", True, "已写入: a.py (100 bytes)")
        text = _render_text(card)
        assert "write_file" in text
        assert "a.py" in text

    def test_failure_is_panel(self):
        """失败 → 紧凑红色 Panel"""
        card = ToolResultCard("command", False, "exec failed",
                              error="Permission denied")
        text = _render_text(card)
        assert "command" in text
        assert "失败" in text

    def test_permission_denied_is_panel(self):
        card = ToolResultCard("delete_file", False, "blocked",
                              permission_denied=True)
        text = _render_text(card)
        assert "拒绝" in text

    def test_circuit_breaker_is_panel(self):
        card = ToolResultCard("command", False, "cooling down",
                              circuit_breaker_tripped=True)
        text = _render_text(card)
        assert "断路器" in text


class TestThinkingCard:
    """ThinkingCard tests — 纯 dim 文本，无边框。"""

    def test_compact_thinking(self):
        card = ThinkingCard("这个文件需要修改才能适配新 API")
        text = _render_text(card)
        assert "这个文件" in text or "🤔" in text

    def test_full_thinking_with_step(self):
        card = ThinkingCard("深入分析:", step_number=3)
        text = _render_text(card)
        assert "3" in text or "深入分析" in text

    def test_long_thought_truncation(self):
        long_thought = "x" * 600
        card = ThinkingCard(long_thought)
        text = _render_text(card)
        # 应从 600 字符截断
        assert len(text) < 600 + 200  # +200 for markup overhead


class TestStepCard:
    """StepCard tests — 纯文本行，无边框。"""

    def test_step_running(self):
        card = StepCard(1, 3, "创建文件", status="running")
        text = _render_text(card)
        assert "1/3" in text
        assert "创建文件" in text

    def test_step_done(self):
        card = StepCard(2, 3, "编辑完成", status="done")
        text = _render_text(card)
        assert "2/3" in text
        assert "编辑完成" in text

    def test_step_failed(self):
        card = StepCard(3, 3, "部署失败", status="failed")
        text = _render_text(card)
        assert "3/3" in text


class TestErrorCard:
    """ErrorCard tests — 保留紧凑 Panel。"""

    def test_error_card(self):
        card = ErrorCard("连接失败: timeout")
        text = _render_text(card)
        assert "连接失败" in text

    def test_warning_card(self):
        card = ErrorCard("磁盘空间不足", title="警告", is_warning=True)
        text = _render_text(card)
        assert "警告" in text

    def test_error_with_details(self):
        card = ErrorCard("执行失败", details="FileNotFoundError at line 42")
        text = _render_text(card)
        assert "执行失败" in text
        assert "FileNotFoundError" in text


class TestApprovalCard:
    """ApprovalCard tests — 保留边框（关键交互节点）。"""

    def test_write_approval_card(self):
        card = ApprovalCard("write_file", "a.py, 100 chars")
        text = _render_text(card)
        assert "OmniAgent" in text or "写入" in text
        assert "a.py" in text
        assert "y" in text
        assert "a" in text
        assert "n" in text

    def test_command_approval_card(self):
        card = ApprovalCard("command", "pip install requests")
        text = _render_text(card)
        assert "命令" in text

    def test_approval_card_with_cache(self):
        card = ApprovalCard("write_file", "a.py", always_approved_count=3)
        text = _render_text(card)
        assert "3" in text


class TestModeHeader:
    """ModeHeader tests — Rule 分隔线，无 Panel。"""

    def test_react_mode(self):
        header = ModeHeader("ReAct", iterations=10)
        text = _render_text(header)
        assert "ReAct" in text
        assert "10" in text

    def test_plan_execute_mode(self):
        header = ModeHeader("Plan-Execute")
        text = _render_text(header)
        assert "Plan-Execute" in text

    def test_reflection_mode(self):
        header = ModeHeader("Reflection")
        text = _render_text(header)
        assert "Reflection" in text

    def test_novel_mode(self):
        header = ModeHeader("Novel")
        text = _render_text(header)
        assert "Novel" in text


class TestShortcutBar:
    """Shortcut bar tests — 纯 dim 文本，无边框。"""

    def test_render_shortcut_bar(self):
        bar = render_shortcut_bar()
        # 验证返回 Text 对象（不再是 Panel）
        assert isinstance(bar, RichText)
        text = _render_text(bar)
        assert len(text) > 0
        assert "Ctrl+C" in text


class TestToolIcons:
    """Icon mapping tests."""

    def test_core_tools_have_icons(self):
        for tool in ["read_file", "write_file", "edit_file", "command", "git"]:
            assert tool in TOOL_ICONS, f"Missing icon for {tool}"
            assert TOOL_ICONS[tool] != ""

    def test_notify_tools_have_icons(self):
        notify = {"write_file", "edit_file", "command", "git", "delete_file"}
        for tool in notify:
            assert tool in TOOL_ICONS, f"Notify tool {tool} missing icon"
