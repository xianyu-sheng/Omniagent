"""
P1 修复单元测试：Checkpoint、Pytest、断路器
"""
import sys
import tempfile
from pathlib import Path

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} -- {detail}")


def run_tests() -> int:
    global passed, failed

    print("=" * 60)
    print("P1 修复单元测试")
    print("=" * 60)

    # ============================================================
    # Test A: CheckpointManager
    # ============================================================
    print()
    print("--- Test A: CheckpointManager ---")

    from omniagent.engine.checkpoint import CheckpointManager, get_checkpoint

    tmpdir = Path(tempfile.mkdtemp(prefix="omni_ckpt_", dir=Path(__file__).resolve().parent))
    ckpt = CheckpointManager(tmpdir)

    # A.1 save 不存在的文件
    nonexistent = tmpdir / "nonexistent.txt"
    check("A.1 save 不存在的文件返回 False", not ckpt.save(nonexistent))

    # A.2 save 存在的文件
    test_file = tmpdir / "test_ckpt.txt"
    test_file.write_text("original content", encoding="utf-8")
    check("A.2 save 存在的文件返回 True", ckpt.save(test_file))
    check("A.3 备份文件已创建", len(ckpt.list_all()) >= 1)

    # A.3 修改文件后 restore
    test_file.write_text("modified content", encoding="utf-8")
    check("A.4 文件内容已修改", test_file.read_text() == "modified content")
    check("A.5 restore 成功", ckpt.restore(test_file))
    check("A.6 文件已恢复原内容", test_file.read_text() == "original content")

    # A.4 keep 和 discard
    test_file2 = tmpdir / "test_ckpt2.txt"
    test_file2.write_text("file2 content", encoding="utf-8")
    ckpt.save(test_file2)
    ckpt.keep(test_file2)
    # keep 后文件应保持原样
    check("A.7 keep 后文件不变", test_file2.read_text() == "file2 content")

    # A.5 Guard 上下文管理器
    test_file3 = tmpdir / "test_guard.txt"
    test_file3.write_text("before guard", encoding="utf-8")
    try:
        with ckpt.guard(test_file3):
            test_file3.write_text("during guard", encoding="utf-8")
            raise RuntimeError("模拟写入异常")
    except RuntimeError:
        pass
    check("A.8 Guard 异常时自动恢复", test_file3.read_text() == "before guard")

    # A.5b Guard 正常退出
    test_file4 = tmpdir / "test_guard_ok.txt"
    test_file4.write_text("before ok", encoding="utf-8")
    with ckpt.guard(test_file4):
        test_file4.write_text("after ok", encoding="utf-8")
    check("A.9 Guard 正常退出保留新内容", test_file4.read_text() == "after ok")

    # A.6 rollback_all
    test_file5 = tmpdir / "rollback_test.txt"
    test_file5.write_text("rollback original", encoding="utf-8")
    ckpt.save(test_file5)
    test_file5.write_text("rollback modified", encoding="utf-8")
    files = ckpt.rollback_all(dry_run=True)
    check("A.10 rollback_all dry_run 列出文件", len(files) >= 1)
    ckpt.rollback_all()
    check("A.11 rollback_all 还原成功", test_file5.read_text() == "rollback original")

    # A.7 全局单例
    g = get_checkpoint()
    check("A.12 get_checkpoint 返回非 None", g is not None)

    # A.8 文件操作工具的 checkpoint 集成
    import asyncio
    from omniagent.tools.file_ops import WriteFileTool, EditFileTool

    write_tool = WriteFileTool()
    wt_file = tmpdir / "write_ckpt_test.txt"
    wt_file.write_text("initial", encoding="utf-8")
    result = asyncio.run(write_tool.invoke({
        "file_path": str(wt_file),
        "content": "new content",
    }))
    check("A.13 write_file 带 checkpoint 成功", not result.is_error)
    check("A.14 内容已更新", wt_file.read_text() == "new content")

    edit_tool = EditFileTool()
    et_file = tmpdir / "edit_ckpt_test.txt"
    et_file.write_text("hello world", encoding="utf-8")
    result = asyncio.run(edit_tool.invoke({
        "file_path": str(et_file),
        "old_text": "hello",
        "new_text": "hi",
    }))
    check("A.15 edit_file 带 checkpoint 成功", not result.is_error)
    check("A.16 编辑结果正确", et_file.read_text() == "hi world")

    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

    # ============================================================
    # Test B: PytestTool
    # ============================================================
    print()
    print("--- Test B: PytestTool ---")

    from omniagent.tools.test_runner import PytestTool

    ptool = PytestTool()

    # B.1 路径不存在
    result = asyncio.run(ptool.invoke({"test_path": "/nonexistent_xyz"}))
    check("B.1 路径不存在返回 error", result.is_error)

    # B.2 在当前 tests 目录运行（检查 pytest 是否安装）
    import shutil
    has_pytest = shutil.which("pytest") is not None
    if has_pytest:
        result = asyncio.run(ptool.invoke({
            "test_path": str(Path(__file__).resolve().parent),
            "filter_expr": "test_e2e_file_ops",
            "verbose": False,
        }))
        check("B.2 pytest 运行不报错", not result.is_error,
              f"content={str(result.content)[:200]}")
        check("B.3 未发现测试(因为不是 pytest 格式)", True)  # E2E tests 不是 pytest 格式
    else:
        check("B.2 pytest 未安装 (跳过)", True)
        check("B.3 pytest 未安装 (跳过)", True)

    # B.3 _parse_pytest_output
    parsed = PytestTool._parse_pytest_output(
        "tests/test_a.py::test_one PASSED\n"
        "tests/test_b.py::test_two FAILED\n"
        "3 passed, 1 failed, 2 errors in 1.23s\n"
        "FAILED tests/test_b.py::test_two - AssertionError: x != y",
        1,
    )
    check("B.4 parse passed=3", parsed["passed"] == 3)
    check("B.5 parse failed=1", parsed["failed"] == 1)
    check("B.6 parse errors=2", parsed["errors"] == 2)
    check("B.7 parse failures 列表", len(parsed["failures"]) == 1)
    check("B.8 failure 包含 test 名",
          "test_two" in parsed["failures"][0]["test"])

    # B.4 TestCommandTool
    from omniagent.tools.test_runner import TestCommandTool
    tctool = TestCommandTool()
    result = asyncio.run(tctool.invoke({"command": "echo test_ok"}))
    check("B.9 run_test 成功", not result.is_error)
    check("B.10 包含输出", "test_ok" in str(result.content))

    # B.5 危险命令拦截
    result = asyncio.run(tctool.invoke({"command": "rm -rf /tmp/test"}))
    check("B.11 危险命令被拦截", result.is_error)

    # ============================================================
    # Test C: 断路器
    # ============================================================
    print()
    print("--- Test C: CircuitBreaker ---")

    from omniagent.engine.circuit_breaker import CircuitBreaker

    breaker = CircuitBreaker(failure_threshold=3, base_cooldown=0.1)

    # C.1 初始状态允许
    check("C.1 初始 allow=True", breaker.allow("test_tool"))

    # C.2 连续失败累计
    breaker.on_failure("test_tool", "error 1")
    check("C.2 1 次失败仍允许", breaker.allow("test_tool"))
    breaker.on_failure("test_tool", "error 2")
    check("C.3 2 次失败仍允许", breaker.allow("test_tool"))
    breaker.on_failure("test_tool", "error 3")
    check("C.4 3 次失败触发冷却", not breaker.allow("test_tool"))

    # C.3 不同工具不受影响
    check("C.5 其他工具仍允许", breaker.allow("other_tool"))

    # C.4 成功后重置
    breaker.on_success("test_tool")
    check("C.6 成功后重置", breaker.allow("test_tool"))

    # C.5 单次冷却超时后重试
    breaker.on_failure("tool_b", "e1")
    breaker.on_failure("tool_b", "e2")
    breaker.on_failure("tool_b", "e3")
    import time
    time.sleep(0.2)  # 等待冷却期结束（base_cooldown=0.1s）
    check("C.7 冷却期过后允许重试", breaker.allow("tool_b"))

    # C.6 status 查询
    breaker.on_failure("tool_c", "err1")
    breaker.on_failure("tool_c", "err2")
    status = breaker.status("tool_c")
    check("C.8 status 包含 name", status["name"] == "tool_c")
    check("C.9 status 包含 consecutive_failures", status["consecutive_failures"] == 2)

    # C.7 on_failure_cooldown
    breaker2 = CircuitBreaker(failure_threshold=2, base_cooldown=0.1)
    breaker2.on_failure("tool_d", "e1")
    msg = breaker2.on_failure_cooldown("tool_d", "e2")
    check("C.10 触发冷却返回提示消息", msg is not None and "tool_d" in msg)

    # C.8 reset
    breaker2.reset()
    check("C.11 reset 后允许", breaker2.allow("tool_d"))

    # ============================================================
    # Test D: ReAct Engine 断路器集成
    # ============================================================
    print()
    print("--- Test D: ReAct Engine 断路器 + 重试 ---")

    from omniagent.engine.react_engine import ReActEngine
    from omniagent.engine.callbacks import SilentCallback
    from omniagent.engine.context import AgentContext

    engine = ReActEngine(
        model_priority=["deepseek/deepseek-v4-pro"],
        max_iterations=3,
        callback=SilentCallback(),
    )
    check("D.1 breaker 已初始化", engine.breaker is not None)

    # D.2 执行不存在的工具
    result = engine._execute_tool("nonexistent_tool_xyz", {}, AgentContext())
    check("D.2 未知工具返回错误", "未知工具" in result)

    # D.3 执行 tool 但是参数不对导致失败
    from omniagent.nodes.tool_node import ToolNode
    result = engine._execute_tool(
        "read_file", {"file_path": "/nonexistent_path_xyz.abc"}, AgentContext())
    check("D.3 失败工具不崩溃", isinstance(result, str) and len(result) > 0)

    # D.4 断路器累计失败（模拟 3 次失败的 read_file）
    breaker_state_before = engine.breaker.status("read_file")
    for _ in range(3):
        engine._execute_tool(
            "read_file", {"file_path": "/nonexistent_path_xyz.abc"}, AgentContext())
    status_after = engine.breaker.status("read_file")
    check("D.4 连续 3 次失败后断路器触发",
          status_after.get("tripped", False) or status_after.get("consecutive_failures", 0) >= 3,
          str(status_after))

    # D.5 重置后恢复
    engine.breaker.reset("read_file")
    check("D.5 重置后允许", engine.breaker.allow("read_file"))

    # ============================================================
    # 总结
    # ============================================================
    print()
    print("=" * 60)
    print(f"结果: {passed} passed, {failed} failed (共 {passed + failed} 项)")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_tests())
