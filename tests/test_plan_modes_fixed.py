"""验证 Plan-Execute 和 Plan+React 修复后效果"""
import sys, io, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from omniagent.engine.plan_execute_engine import PlanExecuteEngine
from omniagent.engine.combined_engines import PlanReactEngine
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
        self.label = label; self.actions = []; self.warnings = []; self.steps = []
    def on_act(self, a, p): self.actions.append((a,p))
    def on_warning(self, m): self.warnings.append(m)
    def on_step(self, sid, t, task): print(f"  Step {sid}/{t}: {task[:120]}")
    def on_step_done(self, sid, ok, s): self.steps.append((sid, ok, s)); print(f"    [{'OK' if ok else 'FAIL'}] {s[:150]}")
    def on_finish(self, r): self.result = r

MODEL = ["deepseek/deepseek-v4-pro"]

for name, engine_cls, kwargs in [
    ("Plan-Execute", PlanExecuteEngine, {"model_priority": MODEL, "max_steps": 15}),
    ("Plan+React", PlanReactEngine, {"model_priority": MODEL, "max_steps": 10, "react_iterations": 6}),
]:
    print(f"\n{'='*60}")
    print(f"  模式: {name}")
    print(f"{'='*60}")
    cb = CB(name)
    ctx = AgentContext()
    t0 = time.time()
    try:
        engine = engine_cls(**kwargs, callback=cb)
        result = engine.run(TASK, context=ctx)
        elapsed = time.time() - t0

        q_checks = [
            ("tools>=5", len(cb.actions) >= 5),
            ("list_files", any(a[0]=="list_files" for a in cb.actions)),
            ("read_file>=3", sum(1 for a in cb.actions if a[0]=="read_file") >= 3),
            ("result>500", len(result) > 500),
            ("not_hollow", not result.strip().startswith(("继续","我将","接下来"))),
            ("substance", any(m in result for m in ["##","技术栈","架构","改进","Flask","Python"])),
            ("no_guessed_files", not any(bad in str(cb.actions) for bad in ["voice_calendar.py","calendar_utils.py","语音日历.py"])),
        ]
        print(f"\n  [{name}] {len(cb.actions)}tools {len(cb.warnings)}warnings {len(result)}chars {elapsed:.0f}s")
        all_ok = True
        for check_name, ok in q_checks:
            if not ok: all_ok = False
            print(f"    {check_name}: {'PASS' if ok else 'FAIL'}")
        print(f"  Overall: {'PASS' if all_ok else 'FAIL'}")

    except Exception as e:
        print(f"  [{name}] FAILED: {e}")
        import traceback; traceback.print_exc()
