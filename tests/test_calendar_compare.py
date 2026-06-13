"""OmniAgent 分析日历项目 — 对比实验用"""
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from omniagent.engine.react_engine import ReActEngine
from omniagent.engine.callbacks import EngineCallback


def _safe(text: str, max_len: int = 500) -> str:
    """Safe console output: strip non-ASCII emoji and truncate."""
    # Remove characters that can't be encoded in GBK
    result = []
    for ch in text[:max_len]:
        try:
            ch.encode("gbk")
            result.append(ch)
        except UnicodeEncodeError:
            cat = unicodedata.category(ch)
            if cat.startswith(("L", "N", "P", "Z")):
                result.append(ch)  # Keep letters, numbers, punctuation, spaces
            else:
                result.append("?")  # Replace emoji/symbols
    return "".join(result)


class VerboseCallback(EngineCallback):
    def __init__(self):
        self.thoughts = []
        self.actions = []
        self.observations = []
        self.warnings = []
        self.parse_errors = 0

    def on_think(self, thought: str) -> None:
        self.thoughts.append(thought)
        print(f"\n[THINK] {_safe(thought, 500)}")

    def on_act(self, action: str, params: dict) -> None:
        self.actions.append(action)
        print(f"\n[ACT] {action}({_safe(str(params), 300)})")

    def on_observe(self, observation: str) -> None:
        self.observations.append(observation)
        obs_short = _safe(observation, 600)
        if len(observation) > 600:
            obs_short += "..."
        print(f"[OBSERVE] {obs_short}")

    def on_warning(self, message: str) -> None:
        self.warnings.append(message)
        self.parse_errors += 1
        print(f"\n[WARN] {_safe(message, 300)}")

    def on_finish(self, result: str) -> None:
        print(f"\n[FINISH]\n{_safe(result, 8000)}")


def main():
    print("=" * 60)
    print("OmniAgent 分析: D:\\语音版的日历工具")
    print("=" * 60)

    callback = VerboseCallback()
    engine = ReActEngine(
        model_priority=["deepseek/deepseek-v4-pro"],
        max_iterations=15,
        callback=callback,
    )

    task = (
        "请分析本地项目 D:\\语音版的日历工具，按以下步骤执行：\n"
        "1. 用 list_files 列出项目根目录 D:\\语音版的日历工具 的结构\n"
        "2. 用 list_files 探索子目录（如 backend、frontend、src 等）\n"
        "3. 用 read_file 读取关键源码文件（路径必须来自 list_files 的真实输出）\n"
        "4. 用 search_files 搜索关键模式（如 class、def、import）\n"
        "5. 基于实际代码在 final_answer 中给出完整分析报告，必须包含：\n"
        "   a) 项目用途和定位\n"
        "   b) 核心架构和模块划分\n"
        "   c) 技术栈\n"
        "   d) 代码质量评估\n"
        "   e) 至少5条具体改进建议\n"
        "重要：final_answer 中必须包含完整报告内容！"
    )

    try:
        result = engine.run(task)
        print(f"\n{'=' * 60}")
        print(f"Done! tool_calls={len(callback.actions)} parse_errors={callback.parse_errors}")
        print(f"{'=' * 60}")
        print(f"\n=== OMNIGENT FINAL OUTPUT ===\n{_safe(result, 10000)}")
        return 0
    except Exception as e:
        print(f"\nFAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
