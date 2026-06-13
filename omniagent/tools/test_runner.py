"""测试运行工具 — PytestTool + TestCommandTool。

Agent 写完代码后自动运行测试验证:
- PytestTool: 调用 pytest，解析结果
- TestCommandTool: 执行任意测试命令
"""

from __future__ import annotations

import contextlib
import logging
import re
import subprocess
from pathlib import Path
from typing import Any

from omniagent.tools.base import BaseTool, ToolResult
from omniagent.tools.file_ops import _validate_path

logger = logging.getLogger(__name__)


class PytestTool(BaseTool):
    """运行 pytest 测试并解析结果。

    支持指定测试文件、目录、或筛选表达式。
    解析输出中的 PASSED/FAILED/ERROR 统计。
    """

    name = "pytest"
    description = (
        "运行 pytest 测试框架。自动发现并执行测试，返回通过/失败/错误统计。"
        "写完代码后应使用此工具验证代码是否正确。"
        "支持参数: 测试路径、-k 筛选、-x 遇错停止、-v 详细输出、--tb 错误格式。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "test_path": {"type": "string", "description": "测试文件/目录路径，默认 tests/", "default": "tests/"},
            "filter_expr": {"type": "string", "description": "pytest -k 筛选表达式，如 'test_move or test_copy'（可选）"},
            "stop_on_fail": {"type": "boolean", "description": "第一个失败即停止（-x），默认 false"},
            "verbose": {"type": "boolean", "description": "详细输出（-v），默认 true"},
            "traceback": {"type": "string", "description": "错误输出格式: short/long/native/no，默认 short"},
        },
        "required": [],
    }

    async def invoke(self, params: dict[str, object]) -> ToolResult:
        test_path = str(params.get("test_path", "tests/") or "tests/")
        filter_expr = str(params.get("filter_expr", "") or "")
        stop_on_fail = bool(params.get("stop_on_fail", False))
        verbose = bool(params.get("verbose", True))
        traceback = str(params.get("traceback", "short") or "short")

        # 验证路径
        try:
            root = _validate_path(test_path, for_write=False)
        except ValueError:
            root = Path(test_path)
        if not root.exists():
            return ToolResult.error(f"测试路径不存在: {root}")

        # 构建 pytest 命令
        cmd = ["pytest", str(root)]
        if verbose:
            cmd.append("-v")
        if stop_on_fail:
            cmd.append("-x")
        if traceback != "short":
            cmd.extend(["--tb", traceback])
        else:
            cmd.extend(["--tb", "short"])
        if filter_expr:
            cmd.extend(["-k", filter_expr])
        # 添加颜色控制
        cmd.extend(["--color", "no"])

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,  # 2 分钟超时
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired:
            return ToolResult.timeout("pytest", 120)
        except FileNotFoundError:
            return ToolResult.error(
                "pytest 未安装。请运行: pip install pytest",
                error_type="runtime_error",
            )

        # 解析 pytest 输出
        output = proc.stdout.strip() or proc.stderr.strip()
        parsed = self._parse_pytest_output(output, proc.returncode)

        # 构建可读摘要
        summary_parts = []
        if parsed["passed"] > 0:
            summary_parts.append(f"✅ {parsed['passed']} passed")
        if parsed["failed"] > 0:
            summary_parts.append(f"❌ {parsed['failed']} failed")
        if parsed["errors"] > 0:
            summary_parts.append(f"⚠️ {parsed['errors']} errors")
        if parsed["skipped"] > 0:
            summary_parts.append(f"⏭️ {parsed['skipped']} skipped")

        summary = " | ".join(summary_parts) if summary_parts else "0 tests"

        # 提取失败详情
        failures = parsed.get("failures", [])

        return ToolResult.ok(
            f"{summary}\n\n{parsed['summary_line']}",
            passed=parsed["passed"],
            failed=parsed["failed"],
            errors=parsed["errors"],
            skipped=parsed["skipped"],
            returncode=proc.returncode,
            failures=failures[:10],  # 最多 10 个失败详情
            raw_summary=parsed["summary_line"],
        )

    @staticmethod
    def _parse_pytest_output(output: str, returncode: int) -> dict[str, Any]:
        """解析 pytest 输出。"""
        result: dict[str, Any] = {
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "summary_line": "",
            "failures": [],
        }

        # 匹配短摘要行: "3 passed, 1 failed, 2 errors"
        short_match = re.search(
            r"(\d+)\s+passed[,\s]*(\d+)\s+failed[,\s]*(\d+)\s+error[s]?",
            output,
            re.IGNORECASE,
        )
        if not short_match:
            short_match = re.search(
                r"(\d+)\s+passed[,\s]*(\d+)\s+failed",
                output,
                re.IGNORECASE,
            )
        if short_match:
            with contextlib.suppress(IndexError, ValueError):
                result["passed"] = int(short_match.group(1))
            with contextlib.suppress(IndexError, ValueError):
                result["failed"] = int(short_match.group(2))
            with contextlib.suppress(IndexError, ValueError):
                result["errors"] = int(short_match.group(3))

        # 匹配跳过的测试
        skipped_match = re.search(r"(\d+)\s+skipped", output, re.IGNORECASE)
        if skipped_match:
            with contextlib.suppress(IndexError, ValueError):
                result["skipped"] = int(skipped_match.group(1))

        # 匹配单行摘要
        summary_match = re.search(r"(=+.*=+)", output)
        if summary_match:
            result["summary_line"] = summary_match.group(1)

        # 提取失败测试详情
        # FAILED 行格式: FAILED tests/test_xxx.py::TestClass::test_name - ErrorMessage
        for line in output.split("\n"):
            if line.strip().startswith("FAILED "):
                parts = line.strip()[7:].strip().split(" - ", 1)
                failure = {"test": parts[0].strip()}
                if len(parts) > 1:
                    failure["error"] = parts[1].strip()[:300]
                result["failures"].append(failure)

        # 如果没有 summary_line，用最后一行
        if not result["summary_line"] and output.strip():
            lines = output.strip().split("\n")
            result["summary_line"] = lines[-1][:200]

        return result


class TestCommandTool(BaseTool):
    """执行任意测试命令并解析结果。

    适用于 pytest 以外的测试框架: unittest, go test, cargo test, npm test 等。
    """

    name = "run_test"
    description = (
        "执行任意测试命令并返回结果。适用于 pytest 以外的测试框架。"
        "命令在工作目录下执行，超时默认 2 分钟。"
        "成功返回 stdout，失败返回 stderr 和退出码。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "测试命令，如 'python -m unittest discover' 或 'go test ./...'"},
            "timeout_seconds": {"type": "integer", "description": "超时秒数，默认 120", "default": 120},
        },
        "required": ["command"],
    }

    async def invoke(self, params: dict[str, object]) -> ToolResult:
        test_cmd = str(params.get("command", "")).strip()
        timeout_s = int(str(params.get("timeout_seconds", 120)))

        if not test_cmd:
            return ToolResult.schema_error("run_test 需要 command 参数")

        # 安全检查: 防止危险命令
        dangerous = ["rm -rf", "del /f", "format", "mkfs", "dd if=", "> /dev/"]
        cmd_lower = test_cmd.lower()
        for d in dangerous:
            if d.lower() in cmd_lower:
                return ToolResult.permission_denied(f"危险命令被拦截: '{d}'")

        try:
            proc = subprocess.run(
                test_cmd,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                shell=True,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired:
            return ToolResult.timeout("run_test", timeout_s)

        output = proc.stdout.strip()
        errors = proc.stderr.strip()

        if proc.returncode == 0:
            return ToolResult.ok(
                output or "测试通过 (无输出)",
                returncode=0,
                stdout=output[:5000],
            )
        return ToolResult.ok(
            f"测试失败 (exit={proc.returncode})\n\nSTDOUT:\n{output[:2000]}\n\nSTDERR:\n{errors[:2000]}",
            returncode=proc.returncode,
            stdout=output[:5000],
            stderr=errors[:5000],
        )
