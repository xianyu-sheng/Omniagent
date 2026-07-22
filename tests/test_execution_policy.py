"""Regression tests for per-turn side-effect boundaries."""

from __future__ import annotations

import ast

import pytest

from xenon.engine.react_engine import ReActEngine
from xenon.engine.context import AgentContext
from xenon.engine.tool_tracker import ToolExecutionTracker
from xenon.nodes.tool_executor import ToolExecutor, execution_policy_denial
from xenon.repl.code_response import validate_code_response
from xenon.repl.difficulty_estimator import DifficultyEstimator
from xenon.repl.execution_policy import ExecutionLevel, classify_execution_policy
from xenon.repl.model_registry import ModelRegistry
from xenon.repl.prompt_optimizer import detect_intent
from xenon.repl.repl import REPL


@pytest.mark.parametrize(
    "text",
    [
        "使用python为我写一个快速排序的核心算法代码 输出到对话区域 不写入文件",
        "为我写一个python实现的快速排序的核心算法代码，并给出详细注释，输出到对话区域",
        "Write a quicksort implementation. Output it in the chat and do not create files.",
        "写一个 Python 爬虫",
    ],
)
def test_code_generation_without_side_effect_authorization_is_answer_only(text):
    intent = detect_intent(text)
    policy = classify_execution_policy(text, intent=intent)

    assert intent == "write_code"
    assert policy.level is ExecutionLevel.ANSWER_ONLY
    assert policy.requires_tools is False
    assert REPL._detect_tool_need(text, intent=intent) is False
    assert DifficultyEstimator._needs_tools(text, intent) is False
    assert ReActEngine._input_requires_tools(text) is False


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("把代码保存到 /tmp/quicksort.py，不要运行", ExecutionLevel.WRITE),
        ("创建一个 hello.py 文件，内容是 print('hello')", ExecutionLevel.WRITE),
        ("写入 /tmp/quicksort.py，然后运行测试", ExecutionLevel.EXECUTE),
        ("读取 src/main.py 并解释接口", ExecutionLevel.READ_ONLY),
        ("今天苏州天气怎么样", ExecutionLevel.READ_ONLY),
        ("请修复这个 bug", ExecutionLevel.WRITE),
    ],
)
def test_explicit_actions_map_to_their_maximum_level(text, expected):
    policy = classify_execution_policy(text, intent=detect_intent(text))

    assert policy.level is expected
    assert policy.requires_tools is True


def test_chat_only_constraint_wins_over_execute_words():
    text = "给出可运行并通过测试的 Python 代码，只输出到对话中，不写入文件，也不要执行"
    policy = classify_execution_policy(text, intent="write_code")

    assert policy.level is ExecutionLevel.ANSWER_ONLY
    assert policy.explicit_no_write is True
    assert policy.explicit_no_execute is True


def test_valid_raw_python_is_normalized_to_a_fenced_block():
    checked = validate_code_response(
        "用 Python 写一个加法函数",
        "def add(a: int, b: int) -> int:\n    return a + b",
    )

    assert checked.valid is True
    assert checked.content.startswith("```python\n")
    code = checked.content.removeprefix("```python\n").removesuffix("\n```")
    ast.parse(code)


@pytest.mark.parametrize(
    ("response", "reason_fragment"),
    [
        ("[Any], low: int, high: int) -> int:\n    return low", "Python 代码不完整"),
        ("```python\ndef quick_sort(values):\n    return values", "代码块未闭合"),
        (
            '<||DSML||tool_calls><||DSML||invoke name="write_file">',
            "工具协议",
        ),
    ],
)
def test_corrupted_code_is_rejected_before_render(response, reason_fragment):
    checked = validate_code_response("用 Python 写快速排序", response)

    assert checked.valid is False
    assert reason_fragment in checked.reason


@pytest.mark.parametrize(
    ("authorized", "tool_name", "params", "blocked"),
    [
        (0, "read_file", {"file_path": "README.md"}, True),
        (1, "read_file", {"file_path": "README.md"}, False),
        (1, "write_file", {"file_path": "x.py", "content": "pass"}, True),
        (2, "write_file", {"file_path": "x.py", "content": "pass"}, False),
        (2, "command", {"action": "python x.py"}, True),
        (3, "command", {"action": "python x.py"}, False),
        (1, "mcp_call", {"tool_name": "weather:get"}, False),
        (1, "mcp_call", {"tool_name": "issues:create"}, True),
    ],
)
def test_tool_boundary_is_enforced_below_the_router(
    authorized, tool_name, params, blocked,
):
    context = AgentContext({"_execution_level": authorized})

    reason = execution_policy_denial(tool_name, params, context)

    assert (reason is not None) is blocked


def test_tool_executor_blocks_write_before_toolnode(monkeypatch):
    executed: list[str] = []

    def fake_execute(self, context):
        executed.append(self.action_type)
        return {"success": True, "content": "unexpected"}

    monkeypatch.setattr("xenon.nodes.tool_executor.ToolNode.execute", fake_execute)
    context = AgentContext({"_execution_level": 1})
    tracker = ToolExecutionTracker()

    result = ToolExecutor().execute(
        "write_file",
        {"file_path": "x.py", "content": "pass"},
        context,
        tracker,
        tools={"write_file": {"name": "write_file"}},
    )

    assert result.success is False
    assert "本轮执行策略" in result.observation
    assert executed == []


def test_code_text_that_mentions_a_saved_file_stays_in_direct(monkeypatch):
    registry = ModelRegistry()
    registry.add_model("openai/test", "test")
    repl = REPL(registry=registry, streaming=False)
    repl.ctx_mgr.add_user_message("输出示例代码")
    rendered: list[str] = []
    rerouted: list[str] = []
    monkeypatch.setattr(
        repl,
        "_blocking_response",
        lambda *_args: '```python\nprint("文件已保存")\n```',
    )
    monkeypatch.setattr(
        repl,
        "_render_assistant_text",
        lambda content, **_kwargs: rendered.append(content),
    )
    monkeypatch.setattr(
        repl,
        "_run_react_engine",
        lambda *_args: rerouted.append("react"),
    )

    repl._run_direct(
        "用 Python 输出提示文字",
        ["openai/test"],
        intent="write_code",
        execution_policy=classify_execution_policy(
            "用 Python 输出提示文字",
            intent="write_code",
        ),
    )

    assert rerouted == []
    assert rendered == ['```python\nprint("文件已保存")\n```']
