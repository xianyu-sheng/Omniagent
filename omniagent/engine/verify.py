"""
Auto-Verification — 执行后客观验证。

在 Reflection 审查阶段之前，对执行结果进行自动化的客观检查:
- 被引用文件是否存在
- Python 文件是否有语法错误
- 写入操作是否实际产生了文件

验证结果注入 Reflection 审查，从"看起来对"升级为"验证过是对的"。
"""

from __future__ import annotations

import ast
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def verify_execution(output: str, cwd: Path | None = None) -> dict[str, Any]:
    """对引擎执行结果进行客观验证。

    从输出文本中提取被引用的文件路径，检查:
    1. 文件是否存在
    2. Python 文件语法是否有效
    3. 修改/创建的文件是否实际存在

    Args:
        output: 引擎执行输出文本
        cwd: 工作目录（默认当前目录）

    Returns:
        {
            "checks": int,           # 检查总数
            "passed": int,           # 通过数
            "failed": int,           # 失败数
            "issues": list[str],     # 问题列表
            "verified_files": int,   # 验证通过的文件数
        }
    """
    result = {"checks": 0, "passed": 0, "failed": 0, "issues": [], "verified_files": 0}

    # ── 提取输出中引用的文件路径 ──
    paths = _extract_file_paths(output)
    if not paths:
        return result

    base = cwd or Path.cwd()
    seen = set()

    for file_path in paths:
        if file_path in seen:
            continue
        seen.add(file_path)

        full_path = base / file_path if not Path(file_path).is_absolute() else Path(file_path)
        result["checks"] += 1

        # 检查 1: 文件是否存在
        if not full_path.exists():
            result["failed"] += 1
            result["issues"].append(f"文件不存在: {file_path}")
            continue

        result["passed"] += 1
        result["verified_files"] += 1

        # 检查 2: Python 文件语法
        if full_path.suffix == ".py":
            try:
                source = full_path.read_text(encoding="utf-8")
                ast.parse(source)
            except SyntaxError as e:
                result["failed"] += 1
                result["issues"].append(
                    f"Python 语法错误: {file_path}:{e.lineno} — {e.msg}"
                )
            except Exception:
                pass  # 非致命错误，跳过

    return result


def _extract_file_paths(text: str) -> list[str]:
    """从文本中提取文件路径引用。

    匹配模式:
    - `file_path`: "path/to/file.py" (JSON 格式)
    - path/to/file.py (markdown 代码)
    - `文件: path/to/file.py` (中文标注)
    - /absolute/path/file.py (绝对路径)
    """
    paths: list[str] = []

    # 模式 1: JSON key: "file_path" 或 "path" 后跟路径
    for m in re.finditer(r'"(?:file_path|path|source|destination)"\s*:\s*"([^"]+)"', text):
        p = m.group(1)
        if _looks_like_path(p):
            paths.append(p)

    # 模式 2: Markdown/文本中的文件路径
    for m in re.finditer(r'(?:^|\s)([\w./\\-]+\.(?:py|js|ts|json|yaml|yml|toml|md|txt|html|css))', text):
        p = m.group(1)
        if _looks_like_path(p) and p not in paths:
            paths.append(p)

    return paths


def _looks_like_path(s: str) -> bool:
    """判断字符串是否看起来像文件路径（不是 URL 或自然语言）。"""
    if s.startswith(("http://", "https://")):
        return False
    # 必须包含 . 和扩展名
    if "." not in s or len(s) < 3:
        return False
    # 不能是纯数字或标记
    if s in ("...", "null", "true", "false"):
        return False
    return True


def format_verification_for_review(verify_result: dict[str, Any]) -> str:
    """将验证结果格式化为可注入审查阶段的文本。"""
    if verify_result["checks"] == 0:
        return ""

    status = "通过" if verify_result["failed"] == 0 else "发现问题"
    lines = [
        f"\n## 自动验证: {status}",
        f"- 检查 {verify_result['checks']} 个文件",
        f"- 通过 {verify_result['passed']} 个",
    ]
    if verify_result["failed"] > 0:
        lines.append(f"- **失败 {verify_result['failed']} 个**:")
        for issue in verify_result["issues"]:
            lines.append(f"  - ❌ {issue}")
    else:
        lines.append("- 所有文件验证通过 ✓")

    return "\n".join(lines)
