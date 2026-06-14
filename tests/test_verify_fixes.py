"""
OmniAgent 针对性验证测试
验证修复内容：
1. ReAct 自适应迭代数（项目分析应该用 20 而不是 10）
2. 动态阈值缩放
3. 测试检查器不再误报
"""
import sys
import io
import json
import time
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from rich.console import Console
from rich.table import Table
from rich.rule import Rule

console = Console()
MODEL = ["deepseek/deepseek-v4-pro"]

def test_react_analysis():
    """测试 ReAct 引擎的项目分析能力（使用自适应迭代数）"""
    from omniagent.engine.react_engine import ReActEngine
    from omniagent.engine.context import AgentContext
    from omniagent.repl.repl import REPL

    user_input = (
        "分析 D:\\语音版的日历工具 这个项目的代码质量和架构。"
        "请用 list_files 先了解项目结构，然后读核心文件，给出具体分析。"
        "最终需要包含：项目概述、技术栈、架构分析、代码质量评估、改进建议。"
    )

    # 使用 REPL 的自适应迭代估算
    iterations = REPL._estimate_react_iterations(user_input)
    console.print(f"\n[cyan]自适应迭代数: {iterations}[/cyan]")

    # 使用新的动态缩放
    engine = ReActEngine(
        model_priority=MODEL,
        max_iterations=iterations,
    )
    console.print(f"[dim]阈值: start={engine.exploration_budget_start}, synth={engine.exploration_budget_synthesize}, hurry={engine.hurry_warning_threshold}, force={engine.force_synthesis_threshold}[/dim]")

    ctx = AgentContext()
    t0 = time.time()
    result = engine.run(user_input, context=ctx)
    elapsed = time.time() - t0

    # 质量检查
    # "达到最大迭代次数" header 会在两种情况下出现：
    # 1. 真正的耗尽（旧行为）— 没有实质性分析内容
    # 2. mercy 编译成功后的 fallback header — 有完整的分析内容
    # 我们检查是否有实质性内容，而不只看 header
    is_exhaustion_report = "达到最大迭代次数" in result[:200]
    has_real_content = len(result) > 2000 and any(
        m in result for m in ["技术栈", "架构", "Flask", "Python", "分析", "改进"]
    )
    checks = {
        "not_exhausted_or_has_content": not is_exhaustion_report or has_real_content,
        "has_analysis": any(m in result for m in ["技术栈", "架构", "Flask", "Python", "分析", "改进"]),
        "not_hollow": not result.strip().startswith(("继续", "我将", "接下来")),
        "min_length": len(result) > 500,
        "no_error": not any(m in result for m in ["❌ 错误", "Traceback"]),
    }

    all_ok = all(checks.values())
    status = "✓ PASS" if all_ok else "✗ FAIL"
    color = "green" if all_ok else "red"

    console.print(f"\n[{color}]{status}[/{color}] ({elapsed:.0f}s, {len(result)} chars)")
    for k, v in checks.items():
        console.print(f"  {k}: {'✓' if v else '✗'}")
    console.print(f"\n[dim]Output preview: {result[:500]}[/dim]")
    return all_ok, result


def test_direct_quality():
    """测试 Direct 模式的基础对话质量"""
    from omniagent.utils.llm_client import chat_completion

    tests = [
        ("你好，简单介绍一下你自己", "greeting"),
        ("用Python写一个冒泡排序函数", "code_gen"),
        ("什么是CAP定理？请解释", "knowledge"),
    ]

    results = []
    for user_input, category in tests:
        console.print(f"\n[cyan]测试: {category} — {user_input[:50]}...[/cyan]")
        messages = [
            {"role": "system", "content": "你是 OmniAgent-CLI 的 AI 编程助手。请用中文回答。"},
            {"role": "user", "content": user_input},
        ]

        t0 = time.time()
        for model_id in MODEL:
            try:
                result = chat_completion(model_id, messages, max_tokens=4096, temperature=0.5)
                if result and result.strip():
                    elapsed = time.time() - t0
                    console.print(f"  ✓ {len(result)} chars, {elapsed:.0f}s")
                    console.print(f"  Preview: {result[:150].replace(chr(10), ' ')}...")
                    results.append(("pass", category, result))
                    break
            except Exception as e:
                continue
        else:
            console.print(f"  ✗ All models failed")
            results.append(("fail", category, ""))

    return results


def test_detect_tool_need():
    """测试工具需求检测的准确性"""
    from omniagent.repl.repl import REPL

    test_cases = [
        # (输入, 期望结果, 描述)
        ("今天重庆天气怎么样？", True, "weather query"),
        ("现在几点了？", True, "time query"),
        ("你好，介绍一下自己", False, "greeting"),
        ("什么是设计模式？", False, "knowledge question"),
        ("用Python写一个函数", False, "simple code request (no file op)"),
        ("读取 app.py 文件的内容", True, "file read request"),
        ("帮我创建一个Flask项目", True, "create project"),
        ("分析项目代码质量", False, "analysis (may or may not need tools, depends on context)"),
        ("执行 pytest 测试", True, "run tests"),
        ("git status 看一下", True, "git operation"),
        ("修改 src/main.py 中的配置", True, "file edit"),
        ("搜索包含 'TODO' 的文件", True, "search files"),
        ("列出当前目录的所有 Python 文件", True, "list files"),
        ("周末有什么好玩的？", False, "casual chat"),
        ("解释一下动态规划算法", False, "algorithm explanation"),
        ("创建一个新目录 data", True, "mkdir"),
    ]

    console.print(f"\n[cyan]工具需求检测测试:[/cyan]")
    ok = 0
    for text, expected, desc in test_cases:
        result = REPL._detect_tool_need(text)
        correct = result == expected
        if correct:
            ok += 1
        status = "✓" if correct else "✗"
        color = "green" if correct else "red"
        console.print(f"  [{color}]{status}[/{color}] {desc:30s} expect={expected} got={result} | {text[:50]}")

    console.print(f"\n  准确率: {ok}/{len(test_cases)} ({ok/len(test_cases)*100:.0f}%)")
    return ok, len(test_cases)


if __name__ == "__main__":
    console.print(Rule("🔧 OmniAgent 针对性验证测试"))

    # 测试 1: 工具检测
    console.print(Rule("1. 工具需求检测"))
    detect_ok, detect_total = test_detect_tool_need()

    # 测试 2: Direct 模式质量
    console.print(Rule("2. Direct 模式基础对话"))
    direct_results = test_direct_quality()

    # 测试 3: ReAct 项目分析（核心）
    console.print(Rule("3. ReAct 项目分析（自适应迭代）"))
    react_ok, react_result = test_react_analysis()

    # 汇总
    console.print(Rule("📊 汇总"))
    direct_pass = sum(1 for r in direct_results if r[0] == "pass")
    console.print(f"  工具检测: {detect_ok}/{detect_total}")
    console.print(f"  Direct 对话: {direct_pass}/{len(direct_results)}")
    console.print(f"  ReAct 分析: {'PASS' if react_ok else 'FAIL'}")
