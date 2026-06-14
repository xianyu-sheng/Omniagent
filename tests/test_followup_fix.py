"""
验证 Plan-Execute follow-up 修复：
1. 第一次分析项目（有目录路径）
2. 第二次跟进请求"不够详细"（follow-up 检测 + scout fallback）
"""
import sys, io, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from rich.console import Console
from rich.rule import Rule
console = Console()

from omniagent.engine.plan_execute_engine import PlanExecuteEngine
from omniagent.engine.context import AgentContext
from omniagent.engine.callbacks import EngineCallback

class CB(EngineCallback):
    def __init__(self, label):
        self.label = label
        self.tools = []
        self.warnings = []
        self.think = []
    def on_act(self, a, p): self.tools.append((a, p))
    def on_think(self, t): self.think.append(t[:100])
    def on_warning(self, m): self.warnings.append(m)
    def on_step(self, sid, t, task): print(f"  [{sid}/{t}] {task[:120]}")
    def on_step_done(self, sid, ok, s): print(f"    [{'OK' if ok else 'FAIL'}] {s[:150]}")
    def on_finish(self, r): pass
    def on_observe(self, o): pass

MODEL = ["deepseek/deepseek-v4-pro"]

# 测试 1: follow-up 检测
console.print(Rule("1. Follow-up 检测测试"))
test_cases = [
    ("不够详细，请你输出的更详细一些", True),
    ("更具体一点", True),
    ("请展开说明", True),
    ("能更深入分析吗？", True),
    ("分析 D:\\语音版的日历工具 项目", False),
    ("继续说", True),
    ("还有呢", True),
    ("写一个Python函数", False),
    ("详细", True),  # 短消息无路径
]
for text, expected in test_cases:
    result = PlanExecuteEngine._is_followup(text)
    status = "✓" if result == expected else "✗"
    color = "green" if result == expected else "red"
    console.print(f"  [{color}]{status}[/{color}] expect={expected} got={result} | {text[:50]}")

# 测试 2: 模拟完整 follow-up 流程
console.print(Rule("2. 模拟 follow-up 流程（follow-up + scout fallback）"))

# 先做一次分析（建立对话历史）
ctx = AgentContext()
cb1 = CB("first")
engine1 = PlanExecuteEngine(model_priority=MODEL, max_steps=15, callback=cb1)
result1 = engine1.run(
    "分析 D:\\语音版的日历工具 这个项目的代码质量和架构。"
    "请用 list_files 先了解项目结构，然后读核心文件，给出具体分析。",
    context=ctx,
)
console.print(f"\n[dim]第一次分析: {len(result1)} chars, {len(cb1.tools)} tools[/dim]")
console.print(f"[dim]预览: {result1[:200].replace(chr(10), ' ')}[/dim]")

# 注入对话历史到 context（模拟 REPL 行为）
ctx.set_conversation_messages([
    {"role": "user", "content": "分析 D:\\语音版的日历工具 这个项目的代码质量和架构。"},
    {"role": "assistant", "content": result1[:500]},  # 截断以控制上下文
    {"role": "user", "content": "不够详细，请你输出的更详细一些"},
])

# 第二次调用（follow-up，无目录路径）
console.print(Rule("3. Follow-up 第二次调用（模拟用户 '不够详细'）"))
cb2 = CB("followup")
engine2 = PlanExecuteEngine(model_priority=MODEL, max_steps=10, callback=cb2)
result2 = engine2.run(
    "不够详细，请你输出的更详细一些",
    context=ctx,
)

console.print(f"\n[bold]Follow-up 结果:[/bold] {len(result2)} chars, {len(cb2.tools)} tools")
console.print(f"[dim]预览: {result2[:500].replace(chr(10), ' ')}[/dim]")

# 质量检查
checks = {
    "not_empty_shell": "空壳" not in result2 and "均不存在" not in result2 and "无对应代码" not in result2,
    "not_hollow": not result2.strip().startswith(("我将", "接下来", "继续")),
    "min_length": len(result2) > 100,
    "no_hallucination": not all(m in result2 for m in ["不存在", "未创建", "缺失"]),
}
console.print()
all_ok = True
for k, v in checks.items():
    c = "green" if v else "red"
    console.print(f"  [{c}]{'✓' if v else '✗'}[/{c}] {k}")
    if not v: all_ok = False
console.print(f"\n[bold]{'✓ 全部通过' if all_ok else '✗ 存在失败'}[/bold]")
