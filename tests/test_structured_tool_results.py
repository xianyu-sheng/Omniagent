"""第一阶段：统一 ToolResult 协议和分页回归测试。"""

from __future__ import annotations

from pathlib import Path

from xenon.engine.context import AgentContext
from xenon.nodes.tool_executor import ToolExecuteResult, ToolExecutor
from xenon.nodes.tool_node import ToolNode
from xenon.nodes.tool_result import TOOL_RESULT_SCHEMA_VERSION, ToolResult


def test_tool_result_normalizes_file_list_and_preserves_counts():
    result = ToolResult.from_raw(
        "list_files",
        {
            "action_type": "list_files",
            "path": "/tmp/project",
            "files": ["a.py", "b.py"],
            "count": 12,
            "returned_count": 2,
            "next_cursor": "2",
            "success": True,
        },
    )

    assert result.schema_version == TOOL_RESULT_SCHEMA_VERSION
    assert result.kind == "file_list"
    assert result.records == ["a.py", "b.py"]
    assert result.total == 12
    assert result.matched == 2
    assert result.truncated is True
    assert result.next_cursor == "2"


def test_tool_execute_result_always_exposes_structured_failure():
    result = ToolExecuteResult(
        "web_fetch",
        False,
        "工具执行失败: 超时",
        error="超时",
    )

    assert result.structured is not None
    assert result.structured.kind == "web_document"
    assert result.structured.success is False
    assert result.structured.error == "超时"


def test_list_files_cursor_returns_stable_pages(tmp_path: Path):
    for name in ("c.py", "a.py", "b.py", "d.txt"):
        (tmp_path / name).write_text(name, encoding="utf-8")

    first = ToolNode(
        "list",
        action_type="list_files",
        file_path=str(tmp_path),
        pattern="*.py",
        limit=2,
    ).execute(AgentContext())
    second = ToolNode(
        "list",
        action_type="list_files",
        file_path=str(tmp_path),
        pattern="*.py",
        limit=2,
        cursor=first["next_cursor"],
    ).execute(AgentContext())

    assert first["schema_version"] == TOOL_RESULT_SCHEMA_VERSION
    assert first["files"] == [str(tmp_path / "a.py"), str(tmp_path / "b.py")]
    assert first["count"] == 3
    assert first["returned_count"] == 2
    assert first["truncated"] is True
    assert first["next_cursor"] == "2"
    assert second["files"] == [str(tmp_path / "c.py")]
    assert second["next_cursor"] is None
    assert second["tool_result"]["records"] == [str(tmp_path / "c.py")]


def test_search_files_cursor_is_structured(tmp_path: Path):
    for index in range(3):
        (tmp_path / f"{index}.txt").write_text("needle\n", encoding="utf-8")

    result = ToolNode(
        "search",
        action_type="search_files",
        file_path=str(tmp_path),
        search_pattern="needle",
        limit=2,
    ).execute(AgentContext())

    assert result["kind"] == "file_search"
    assert result["total"] == 3
    assert result["returned_count"] == 2
    assert result["truncated"] is True
    assert result["next_cursor"] == "2"
    assert len(result["tool_result"]["records"]) == 2


def test_executor_exposes_structured_web_result(monkeypatch):
    def fake_execute(self, _context):
        return {
            "action_type": "web_fetch",
            "url": "https://example.test/timetable",
            "content": "18:04 G1",
            "records": [{"train_no": "G1", "departure": "18:04"}],
            "records_detected": 10,
            "records_matched": 1,
            "prefilter_applied": True,
            "success": True,
        }

    monkeypatch.setattr(ToolNode, "execute", fake_execute)
    result = ToolExecutor().execute(
        "web_fetch",
        {"url": "https://example.test/timetable"},
        AgentContext(),
        tools={"web_fetch": {"name": "web_fetch"}},
    )

    assert result.success is True
    assert result.structured is not None
    assert result.structured.kind == "web_document"
    assert result.structured.total == 10
    assert result.structured.matched == 1
    assert "type" not in result.structured.filters
