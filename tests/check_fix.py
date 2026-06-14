"""Quick check on test 5.1 with fixed error markers"""
import sys, io, re, time
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from omniagent.engine.react_engine import ReActEngine
from omniagent.engine.context import AgentContext
from omniagent.repl.repl import REPL

MODEL = ["deepseek/deepseek-v4-pro"]
user_input = "分析 D:\\语音版的日历工具 这个项目的代码质量和架构。请用 list_files 先了解项目结构，然后读核心文件，给出具体分析。"
iterations = REPL._estimate_react_iterations(user_input)
engine = ReActEngine(model_priority=MODEL, max_iterations=iterations)
ctx = AgentContext()

print(f"Iterations: {iterations}")
print(f"Thresholds: start={engine.exploration_budget_start}, synth={engine.exploration_budget_synthesize}")

t0 = time.time()
result = engine.run(user_input, context=ctx)
elapsed = time.time() - t0

# Fixed checker logic
output = result
is_structured = (
    len(output) > 1000
    and len(re.findall(r"##|###|\*\*|技术栈|架构|分析|建议", output)) >= 4
)
critical_errors = [
    r"Traceback\s*\(most recent call last\)",
    r"(?:所有模型|全部模型|模型调用).{0,5}(?:失败|不可用|错误)",
]
if is_structured:
    has_error = any(re.search(p, output, re.I) for p in critical_errors)
    print(f"Structured report → critical check only → has_error={has_error}")
else:
    text_no_code = re.sub(r"```[\s\S]*?```", "", output)
    text_no_code = re.sub(r"`[^`]+`", "", text_no_code)
    real_patterns = [
        r"❌\s*(?:错误|失败|异常|Error|Exception|Failed)",
        r"Traceback\s*\(most recent call last\)",
        r"(?:所有模型|全部模型|模型调用).{0,5}(?:失败|不可用|错误)",
    ]
    has_error = any(re.search(p, text_no_code, re.I) for p in real_patterns)
    print(f"Non-report → full check → has_error={has_error}")

print()
print(f"no_error_markers: {'PASS' if not has_error else 'FAIL'}")
print(f"Output: {len(result)} chars, {elapsed:.0f}s")
print(f"First 400 chars: {result[:400]}")
