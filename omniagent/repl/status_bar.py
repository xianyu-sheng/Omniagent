"""
Status Bar — 底部状态栏 (v0.6.0 · Claude Code 风格)。

在终端底部实时显示一条干净的状态行：
- 当前模型 / auto-routing
- Token 使用量（进度条）
- 思考范式
- 工具调用计数
- 会话时长

设计原则：无冗余标签，位置即语义。Claude Code 风格：值 + 分隔符，
不用"模型: xxx"这样的标注格式。
"""

from __future__ import annotations

import shutil
import time as _time
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.markup import escape

if TYPE_CHECKING:
    from omniagent.repl.context_manager import ContextManager
    from omniagent.repl.model_registry import ModelRegistry


class StatusBar:
    """底部状态栏 — Claude Code 风格：一条线，只展示值。"""

    def __init__(
        self,
        console: Console,
        ctx_mgr: ContextManager,
        registry: ModelRegistry,
        *,
        usage_tracker: Any = None,
    ) -> None:
        self.console = console
        self.ctx_mgr = ctx_mgr
        self.registry = registry
        self.usage_tracker = usage_tracker
        self._streaming = True
        self._last_model: str | None = None
        self._auto_router = None
        self._notification: str | None = None
        self._notification_expires: float = 0.0
        self._session_start: float = _time.monotonic()
        self._tool_call_count: int = 0

    # ── 属性设置 ───────────────────────────────────────────

    def set_last_model(self, model_id: str) -> None:
        self._last_model = model_id

    def set_streaming(self, enabled: bool) -> None:
        self._streaming = enabled

    def set_mode_notification(self, mode_name: str) -> None:
        self._notification = f"🔄 {mode_name}"
        self._notification_expires = _time.monotonic() + 3.0

    def add_tool_call(self) -> None:
        self._tool_call_count += 1

    @property
    def tool_call_count(self) -> int:
        return self._tool_call_count

    @property
    def session_elapsed(self) -> float:
        return _time.monotonic() - self._session_start

    # ── 内部工具方法 ───────────────────────────────────────

    def _clear_expired_notification(self) -> None:
        if self._notification and _time.monotonic() > self._notification_expires:
            self._notification = None

    @staticmethod
    def _parse_pct(ratio) -> float:
        try:
            if isinstance(ratio, str):
                return float(ratio.strip('%'))
            return float(ratio) * 100 if ratio <= 1 else float(ratio)
        except (ValueError, TypeError, AttributeError):
            return 0.0

    @staticmethod
    def _fmt_duration(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        if m >= 60:
            h, m = divmod(m, 60)
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    @staticmethod
    def _fmt_tokens(n: int) -> str:
        """人性化 token 数量：1.2k, 12.3k, 1.2M。"""
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}k"
        return str(n)

    def _model_display(self, max_len: int = 28) -> str:
        """获取模型显示名。auto 模式下显示 'auto → model'。"""
        if self._auto_router and not self._auto_router.is_empty():
            active = self._auto_router.get_active_model_id() or self._last_model
            display = f"auto → {active or '—'}"
        else:
            display = self._last_model or "—"
        if len(display) > max_len:
            display = "…" + display[-(max_len - 1):]
        return display

    # ── Panel 渲染（向后兼容，供测试使用）──────────────────

    def render(self) -> Any:
        """返回 Rich Panel（向后兼容旧 API）。

        新代码应使用 ``get_toolbar_text()`` 获取纯文本状态行。
        """
        from rich.panel import Panel as _Panel
        try:
            text = self._toolbar_impl()
            return _Panel(text, style="dim", height=1, padding=(0, 1))
        except Exception:
            return _Panel("[dim]状态不可用[/dim]", style="dim", height=1, padding=(0, 1))

    # ── 主渲染：prompt_toolkit bottom_toolbar ────────────────

    def get_toolbar_text(self) -> str:
        """返回单行状态文本（无标签，值 + 分隔符）。

        Claude Code 风格示例：
          deepseek-v4 · react · 12k/128k (9%) · 🔧3 · ⚡ · 15 msg · 05:32
        """
        try:
            return self._toolbar_impl()
        except Exception:
            return "—"

    def _toolbar_impl(self) -> str:
        stats = self.ctx_mgr.stats()
        mode = self.registry.get_current_mode()
        pct_val = self._parse_pct(stats["usage_ratio"])

        # ── Token 用量（缩略格式） ──
        used_fmt = self._fmt_tokens(stats["estimated_tokens"])
        max_fmt = self._fmt_tokens(stats["max_tokens"])

        # ── Token 微型进度条 ──
        bar_width = 6
        filled = min(int(pct_val / 100 * bar_width), bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)

        # ── 通知 ──
        self._clear_expired_notification()

        # ── 组装部件 ──
        parts: list[str] = []

        # 通知 / 警告（最优先）
        if stats["needs_compact"]:
            parts.append("⚠ /compact")
        if self._notification:
            parts.append(self._notification)
        if self._tool_call_count > 0:
            parts.append(f"🔧{self._tool_call_count}")

        # 核心状态
        parts.append(self._model_display())
        parts.append(f"[{bar}] {used_fmt}/{max_fmt}")

        # 附加信息
        parts.append(mode.name)
        parts.append("⚡" if self._streaming else "⏸")
        parts.append(f"{stats['total_messages']} msg")
        parts.append(self._fmt_duration(self.session_elapsed))

        # undo 提示
        if stats["undo_available"] > 0:
            parts.append(f"↩×{stats['undo_available']}")

        # 缓存命中率 / 费用（需 UsageTracker）
        if self.usage_tracker:
            total_cache = self.usage_tracker.cache_hits + self.usage_tracker.cache_misses
            if total_cache > 0:
                parts.append(f"💾{self.usage_tracker.cache_hit_rate:.0%}")
            if self.usage_tracker.estimated_cost > 0:
                cost = self.usage_tracker.estimated_cost
                parts.append("$<0.01" if cost < 0.01 else f"${cost:.2f}")

        line = " · ".join(parts)
        term_width = shutil.get_terminal_size().columns
        return line[:term_width - 1] if len(line) > term_width else line

    # ── 非 prompt_toolkit 模式（回退） ──────────────────────

    def print_status(self) -> None:
        """非 PT 模式：在输入前打印一行状态。

        注意：在非 PT 模式下状态行位于输入上方（终端限制），
        无法固定在底部。推荐使用 prompt_toolkit 模式。
        """
        try:
            self._print_status_impl()
        except Exception:
            pass  # 静默失败，状态栏不是关键功能

    def _print_status_impl(self) -> None:
        stats = self.ctx_mgr.stats()
        pct_val = self._parse_pct(stats["usage_ratio"])
        used_fmt = self._fmt_tokens(stats["estimated_tokens"])
        max_fmt = self._fmt_tokens(stats["max_tokens"])

        self._clear_expired_notification()

        parts: list[str] = []

        if self._notification:
            parts.append(self._notification)
        if stats["needs_compact"]:
            parts.append("⚠ /compact")

        parts.append(self._model_display(30))
        parts.append(self.registry.get_current_mode().name)
        parts.append(f"Token {used_fmt}/{max_fmt} ({stats['usage_ratio']})")
        if self._tool_call_count > 0:
            parts.append(f"🔧{self._tool_call_count}")
        parts.append(f"{stats['total_messages']} msg")
        parts.append(self._fmt_duration(self.session_elapsed))
        parts.append("⚡" if self._streaming else "⏸")

        line = " · ".join(parts)
        token_color = "red" if pct_val > 80 else ("yellow" if pct_val > 50 else "green")

        self.console.print(f"[dim]  {escape(line)}[/dim]")
