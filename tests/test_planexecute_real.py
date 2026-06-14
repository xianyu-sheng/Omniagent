"""真实运行 PlanExecuteEngine — 与 REPL 使用相同入口"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from omniagent.engine.plan_execute_engine import PlanExecuteEngine
from omniagent.engine.callbacks import EngineCallback


def _safe(text: str, max_len: int = 500) -> str:
    result = []
    for ch in text[:max_len]:
        try: ch.encode("gbk"); result.append(ch)
        except UnicodeEncodeError: result.append("?")
    return "".join(result)


class CB(EngineCallback):
    def __init__(self):
        self.thoughts, self.actions, self.obs, self.warnings = [], [], [], []
        self.step_info = []
    def on_think(self, t): self.thoughts.append(t); print(f"\n[T] {_safe(t, 400)}")
    def on_act(self, a, p): self.actions.append((a, p)); print(f"[A] {a}({_safe(json.dumps(p, ensure_ascii=False), 400)})")
    def on_observe(self, o): self.obs.append(o); s = _safe(o, 600); print(f"[O] {s}{'...' if len(o)>600 else ''}")
    def on_warning(self, m): self.warnings.append(m); print(f"[W] {_safe(m, 400)}")
    def on_step(self, sid, total, task): print(f"\n[S] Step {sid}/{total}: {_safe(task, 200)}")
    def on_step_done(self, sid, ok, summary): self.step_info.append((sid, ok, summary)); print(f"  [{'OK' if ok else 'FAIL'}] {_safe(summary, 300)}")
    def on_error(self, e): print(f"\n[ERR] {_safe(e, 400)}")
    def on_finish(self, r): print(f"\n{'='*60}\n[FINISH] ({len(r)} chars)\n{'='*60}\n{_safe(r, 8000)}")


def main():
    cb = CB()
    engine = PlanExecuteEngine(
        model_priority=["deepseek/deepseek-v4-pro"],
        max_steps=15,
        callback=cb,
    )
    task = (
        "请分析本地项目 D:\\语音版的日历工具，按以下步骤：\n"
        "1. 用 list_files 列出项目目录结构\n"
        "2. 用 read_file 逐个读取核心源文件（基于步骤1的真实输出）\n"
        "3. 给出分析结论：项目用途、技术栈、代码质量、改进建议"
    )
    try:
        result = engine.run(task)
        print(f"\nDone! tools={len(cb.actions)} warnings={len(cb.warnings)} steps={len(cb.step_info)}")

        checks = [
            ("工具调用 >= 3", len(cb.actions) >= 3),
            ("list_files 被调用", any(a[0] == "list_files" for a in cb.actions)),
            ("read_file 被调用", any(a[0] == "read_file" for a in cb.actions)),
            ("结果 > 300 chars", len(result) > 300),
            ("非空洞开头", not result.strip().startswith(("继续", "我将", "接下来", "基于已收集"))),
            ("含实质内容", any(m in result for m in ["##", "###", "技术栈", "架构", "改进", "Flask", "Python"])),
            ("无参数错误", not any("参数错误" in w for w in cb.warnings)),
            ("无 NL-path", not any("自然语言" in w for w in cb.warnings)),
            ("无幻觉文件", "speech_handler.py" not in result and "calendar_utils.py" not in result),
        ]
        print("\n=== 质量检查 ===")
        all_ok = True
        for name, ok in checks:
            if not ok: all_ok = False
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        return 0 if all_ok else 1
    except Exception as e:
        print(f"FAILED: {e}")
        import traceback; traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
