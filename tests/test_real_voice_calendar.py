"""真实运行 OmniAgent ReActEngine 分析 D:\语音版的日历工具"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from omniagent.engine.react_engine import ReActEngine
from omniagent.engine.callbacks import EngineCallback


def _safe(text: str, max_len: int = 500) -> str:
    result = []
    for ch in text[:max_len]:
        try:
            ch.encode("gbk")
            result.append(ch)
        except UnicodeEncodeError:
            result.append("?")
    return "".join(result)


class CB(EngineCallback):
    def __init__(self):
        self.thoughts = []
        self.actions = []
        self.obs = []
        self.warnings = []

    def on_think(self, t: str) -> None:
        self.thoughts.append(t)
        print(f"\n[T] {_safe(t, 500)}")

    def on_act(self, a: str, p: dict) -> None:
        self.actions.append((a, p))
        print(f"[A] {a}({_safe(str(p), 400)})")

    def on_observe(self, o: str) -> None:
        self.obs.append(o)
        s = _safe(o, 600)
        print(f"[O] {s}{'...' if len(o) > 600 else ''}")

    def on_warning(self, m: str) -> None:
        self.warnings.append(m)
        print(f"[W] {_safe(m, 300)}")

    def on_finish(self, r: str) -> None:
        print(f"\n{'='*60}")
        print(f"[FINISH] ({len(r)} chars)")
        print(f"{'='*60}")
        print(_safe(r, 15000))


def main():
    cb = CB()
    engine = ReActEngine(
        model_priority=["deepseek/deepseek-v4-pro"],
        max_iterations=15,
        callback=cb,
    )

    task = (
        "请分析本地项目 D:\\语音版的日历工具，按以下步骤：\n"
        "1. 用 list_files 列出项目目录结构\n"
        "2. 用 read_file 逐个读取核心源文件（app.py, desktop_app.py, requirements.txt 等）\n"
        "3. 在 final_answer 中直接交付完整分析报告，必须包含：\n"
        "   a) 项目用途和定位\n"
        "   b) 核心架构和模块划分\n"
        "   c) 技术栈\n"
        "   d) 代码质量评估（优点和具体问题）\n"
        "   e) 至少5条具体改进建议\n"
        "重要：final_answer 中必须直接包含完整报告，不要描述你将要做什么！"
    )

    try:
        result = engine.run(task)
        print(f"\nDone! tools={len(cb.actions)} warnings={len(cb.warnings)}")

        # 质量检查
        checks = [
            ("工具调用 >= 3", len(cb.actions) >= 3),
            ("list_files", any(a[0] == "list_files" for a in cb.actions)),
            ("read_file", any(a[0] == "read_file" for a in cb.actions)),
            ("结果 > 500 chars", len(result) > 500),
            ("非空洞开头", not result.strip().startswith(("继续", "我将", "我会", "接下来"))),
            ("含结构化内容", any(m in result for m in ["##", "###", "1.", "2.", "技术栈", "架构", "改进"])),
            ("无参数错误", not any("参数错误" in w for w in cb.warnings)),
        ]
        print("\n=== 质量检查 ===")
        for name, ok in checks:
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        return 0 if all(ok for _, ok in checks) else 1
    except Exception as e:
        print(f"FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
