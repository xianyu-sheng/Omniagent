"""Regression tests for Xenon's interactive visual hierarchy."""

from __future__ import annotations

import io
import os

from rich.console import Console

from xenon.repl.context_manager import ContextManager
from xenon.repl.model_registry import ModelRegistry
from xenon.repl.repl import REPL
from xenon.repl.status_bar import StatusBar


def _bar() -> StatusBar:
    return StatusBar(Console(file=io.StringIO()), ContextManager(), ModelRegistry())


def test_toolbar_has_api_model_and_context_fragments():
    fragments = _bar().get_toolbar_fragments()
    assert fragments[0] == ("class:toolbar.danger", "  ○ API /setup")
    assert any(style == "class:toolbar.mode" for style, _ in fragments)
    assert any("context" in text for _, text in fragments)


def test_input_rule_spans_terminal_width(monkeypatch):
    monkeypatch.setattr(
        "xenon.repl.status_bar.shutil.get_terminal_size",
        lambda *a: os.terminal_size((48, 24)),
    )
    fragments = _bar().get_input_rule_fragments()
    assert fragments == [("class:input.rule", "─" * 47)]


def test_prompt_keeps_rule_with_input_and_status_at_screen_bottom():
    repl = REPL()
    assert repl._pt_session is not None
    assert repl._pt_session.bottom_toolbar == repl.status_bar.get_toolbar_fragments

    root = repl._pt_session.app.layout.container
    main = root.children[0]
    main_stack = main.alternative_content.content
    assert main_stack.children[-1].content.text == repl.status_bar.get_input_rule_fragments

    buffer_window = main_stack.children[1].content
    assert buffer_window.height() == 1


def test_toolbar_promotes_compaction_warning():
    bar = _bar()
    bar.ctx_mgr.add_user_message("x" * 200_000)
    fragments = bar.get_toolbar_fragments()
    assert ("class:toolbar.danger", "⚠ /compact") in fragments
