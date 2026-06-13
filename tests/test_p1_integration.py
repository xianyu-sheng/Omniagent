"""P1 集成实测脚本"""
import asyncio, tempfile, shutil
from pathlib import Path

def test():
    print("=" * 50)
    print("P1 Integration Test")

    # 1. Checkpoint save/restore
    print("\n1. Checkpoint")
    from omniagent.engine.checkpoint import CheckpointManager
    tmpdir = Path(tempfile.mkdtemp(prefix="omni_p1_int_", dir=Path.cwd()))
    ckpt = CheckpointManager(tmpdir)
    f = tmpdir / "important.py"
    f.write_text("print('critical code')")
    ckpt.save(f)
    f.write_text("print('broken!!!')")
    ckpt.restore(f)
    assert f.read_text() == "print('critical code')", "RESTORE FAILED"
    print("  OK save+restore")

    # 2. Pytest parse
    print("\n2. Pytest parse")
    from omniagent.tools.test_runner import PytestTool
    parsed = PytestTool._parse_pytest_output(
        "3 passed, 1 failed, 2 errors in 1.23s\nFAILED test_x::f - err", 1)
    assert parsed["passed"] == 3 and parsed["failed"] == 1
    print(f"  OK passed={parsed['passed']} failed={parsed['failed']} errors={parsed['errors']}")

    # 3. Circuit breaker
    print("\n3. Circuit breaker")
    from omniagent.engine.react_engine import ReActEngine
    from omniagent.engine.callbacks import SilentCallback
    from omniagent.engine.context import AgentContext
    engine = ReActEngine(
        model_priority=["deepseek/deepseek-v4-pro"],
        max_iterations=3, callback=SilentCallback())
    for i in range(3):
        engine._execute_tool("read_file", {"file_path": "/bad.xyz"}, AgentContext())
    status = engine.breaker.status("read_file")
    print(f"  failures={status.get('consecutive_failures')}, tripped={status.get('tripped')}")
    engine.breaker.reset()
    assert engine.breaker.allow("read_file")
    print("  OK trigger+reset")

    # 4. WriteFileTool with checkpoint
    print("\n4. WriteFileTool + checkpoint")
    from omniagent.tools.file_ops import WriteFileTool
    wt = WriteFileTool()
    wtf = tmpdir / "write_test.py"
    wtf.write_text("original")
    result = asyncio.run(wt.invoke({"file_path": str(wtf), "content": "updated"}))
    assert not result.is_error, f"Fail: {result.content}"
    assert wtf.read_text() == "updated"
    print("  OK")

    # 5. EditFileTool with checkpoint
    print("\n5. EditFileTool + checkpoint")
    from omniagent.tools.file_ops import EditFileTool
    et = EditFileTool()
    etf = tmpdir / "edit_test.py"
    etf.write_text("hello world")
    result = asyncio.run(et.invoke({"file_path": str(etf), "old_text": "hello", "new_text": "hi"}))
    assert not result.is_error, f"Fail: {result.content}"
    assert etf.read_text() == "hi world"
    print("  OK")

    # 6. PytestTool
    print("\n6. PytestTool")
    ptool = PytestTool()
    result = asyncio.run(ptool.invoke({
        "test_path": "tests/",
        "filter_expr": "test_p1",
        "verbose": False,
    }))
    print(f"  result: {str(result.content)[:200]}")

    # 7. TestCommandTool
    print("\n7. TestCommandTool")
    from omniagent.tools.test_runner import TestCommandTool
    tctool = TestCommandTool()
    result = asyncio.run(tctool.invoke({"command": "python -c \"print('hello test')\""}))
    assert not result.is_error
    assert "hello test" in str(result.content)
    print("  OK")

    shutil.rmtree(tmpdir, ignore_errors=True)
    print("\nALL P1 INTEGRATION TESTS PASSED")
    return 0

if __name__ == "__main__":
    import sys
    sys.exit(test())
