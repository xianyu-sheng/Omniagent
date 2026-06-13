"""OmniAgent 分析本地项目：语音版日历工具 — 端到端验证。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from omniagent.engine.react_engine import ReActEngine
from omniagent.engine.callbacks import EngineCallback


class VerboseCallback(EngineCallback):
    def __init__(self) -> None:
        self.thoughts: list[str] = []
        self.actions: list[str] = []
        self.observations: list[str] = []
        self.warnings: list[str] = []
        self.parse_errors = 0

    def on_think(self, thought: str) -> None:
        self.thoughts.append(thought)
        print(f"\n🧠 [THINK] {thought[:400]}")

    def on_act(self, action: str, params: dict) -> None:
        self.actions.append(action)
        print(f"\n🔧 [ACT] {action}({str(params)[:200]})")

    def on_observe(self, observation: str) -> None:
        self.observations.append(observation)
        obs_short = observation[:500] + ("..." if len(observation) > 500 else "")
        print(f"👁️  [OBSERVE] {obs_short}")

    def on_warning(self, message: str) -> None:
        self.warnings.append(message)
        self.parse_errors += 1
        print(f"\n⚠️  [WARN] {message[:300]}")

    def on_finish(self, result: str) -> None:
        print(f"\n✅ [FINISH]\n{result[:3000]}")


def main() -> int:
    print("=" * 60)
    print("OmniAgent 本地项目分析 — 语音版日历工具")
    print("=" * 60)

    callback = VerboseCallback()
    engine = ReActEngine(
        model_priority=["deepseek/deepseek-v4-pro"],
        max_iterations=15,
        callback=callback,
    )

    task = (
        '请分析本地项目 D:\\语音版的日历工具，步骤如下：\n'
        '1. 用 list_files 列出项目根目录结构\n'
        '2. 继续用 list_files 探索子目录（src、tests 等）\n'
        '3. 用 read_file 读取关键源码文件（路径必须来自 list_files 的真实输出）\n'
        '4. 用 search_files 搜索关键模式（如 class、def、import）\n'
        '5. 基于实际代码给出完整分析报告：\n'
        '   - 项目用途和定位\n'
        '   - 核心架构和模块划分\n'
        '   - 技术栈（语言、框架、依赖）\n'
        '   - 代码质量评估\n'
        '   - 改进建议'
    )

    try:
        result = engine.run(task)
        print(f"\n{'=' * 60}")
        print(f"✅ 执行完成！")
        print(f"{'=' * 60}")
        print(f"\n📊 统计：")
        print(f"   思考: {len(callback.thoughts)}  工具调用: {len(callback.actions)}")
        print(f"   观察: {len(callback.observations)}  警告: {len(callback.warnings)}")
        print(f"   JSON解析错误: {callback.parse_errors}")
        print(f"\n📝 最终结果：\n{result}")

        # 判定标准
        ok = True
        if callback.parse_errors > 0:
            print("\n⚠️  存在 JSON 解析错误！")
            ok = False
        if len(callback.actions) < 3:
            print("\n⚠️  工具调用不足（<3次），分析可能不充分！")
            ok = False
        return 0 if ok else 1

    except Exception as e:
        print(f"\n❌ 执行失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
