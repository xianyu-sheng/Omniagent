"""OmniAgent 多思考模式对比 — 真实运行"""
import sys, io, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from omniagent.engine.react_engine import ReActEngine
from omniagent.engine.plan_execute_engine import PlanExecuteEngine
from omniagent.engine.reflection_engine import ReflectionEngine
from omniagent.engine.combined_engines import PlanReactEngine, PlanReflectionEngine, ReactReflectionEngine
from omniagent.engine.callbacks import EngineCallback
from omniagent.engine.context import AgentContext

TASK = (
    "请分析本地项目 D:\\语音版的日历工具：\n"
    "1. 用 list_files 了解项目结构\n"
    "2. 用 read_file 读取核心源文件\n"
    "3. 给出分析报告：项目用途、技术栈、架构、代码质量（优缺点）、至少5条改进建议\n"
    "重要：final_answer 直接包含完整分析报告！"
)

class CB(EngineCallback):
    def __init__(self, label):
        self.label = label
        self.actions = []; self.warnings = []; self.start = 0
    def on_act(self, a, p): self.actions.append((a,p))
    def on_warning(self, m): self.warnings.append(m)
    def on_finish(self, r): self.result = r

def quality(text, actions, warnings):
    return {
        "tools": len(actions),
        "list_files": any(a[0]=="list_files" for a in actions),
        "read_file": any(a[0]=="read_file" for a in actions),
        "len": len(text),
        "no_hollow": not text.strip().startswith(("继续","我将","接下来","基于已收集")),
        "structure": any(m in text for m in ["##","技术栈","架构","改进","Flask","Python"]),
        "no_param_err": not any("参数错误" in w for w in warnings),
    }

def run_mode(name, engine_cls, **kwargs):
    print(f"\n{'='*70}")
    print(f"  模式 {name} — 运行中...")
    print(f"{'='*70}")
    cb = CB(name)
    ctx = AgentContext()
    t0 = time.time()
    try:
        if "context" in kwargs:
            engine = engine_cls(**{k:v for k,v in kwargs.items() if k!="context"}, callback=cb)
            result = engine.run(TASK, context=ctx)
        else:
            engine = engine_cls(**{k:v for k,v in kwargs.items() if k!="context"}, callback=cb)
            result = engine.run(TASK, context=ctx)
        elapsed = time.time() - t0
        q = quality(result, cb.actions, cb.warnings)
        print(f"\n  [{name}] {len(cb.actions)}工具 {len(cb.warnings)}警告 {len(result)}字 {elapsed:.0f}s")
        for k,v in q.items():
            print(f"    {k}: {'PASS' if v else 'FAIL'}")
        return {"mode": name, "actions": len(cb.actions), "warnings": len(cb.warnings),
                "chars": len(result), "time": elapsed, "quality": q, "preview": result[:400]}
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  [{name}] FAILED: {e} ({elapsed:.0f}s)")
        return {"mode": name, "error": str(e), "time": elapsed}

MODEL = ["deepseek/deepseek-v4-pro"]
results = []

# 1. ReAct
results.append(run_mode("1-ReAct", ReActEngine, model_priority=MODEL, max_iterations=15))

# 2. Plan-Execute
results.append(run_mode("2-PlanExecute", PlanExecuteEngine, model_priority=MODEL, max_steps=12))

# 3. Reflection
results.append(run_mode("3-Reflection", ReflectionEngine, model_priority=MODEL, max_rounds=2))

# 4. Plan+React
results.append(run_mode("4-PlanReact", PlanReactEngine, model_priority=MODEL, max_steps=8, react_iterations=8))

# 5. Plan+Reflection
results.append(run_mode("5-PlanReflection", PlanReflectionEngine, model_priority=MODEL, max_steps=8, review_rounds=2))

# 6. React+Reflection
results.append(run_mode("6-ReactReflection", ReactReflectionEngine, model_priority=MODEL, react_iterations=10, review_rounds=2))

print(f"\n{'='*70}")
print(f"  总结对比")
print(f"{'='*70}")
print(f"{'模式':<25} {'工具':>4} {'警告':>4} {'字数':>6} {'耗时':>6} {'PASS':>5}")
print("-"*60)
for r in results:
    if "error" in r:
        print(f"{r['mode']:<25} {'ERROR':>4} {'':>4} {'':>6} {r['time']:.0f}s")
    else:
        q = r["quality"]
        passes = sum(1 for v in q.values() if v)
        print(f"{r['mode']:<25} {r['actions']:>4} {r['warnings']:>4} {r['chars']:>6} {r['time']:.0f}s {passes}/{len(q)}")
