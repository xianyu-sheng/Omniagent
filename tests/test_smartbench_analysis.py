"""实际调用 OmniAgent 分析 SmartBench 仓库 — 端到端验证 JSON 解析修复。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from omniagent.engine.react_engine import ReActEngine
from omniagent.engine.callbacks import EngineCallback


class VerboseCallback(EngineCallback):
    """逐步骤打印回调，方便追踪执行过程。"""

    def __init__(self) -> None:
        self.thoughts: list[str] = []
        self.actions: list[str] = []
        self.observations: list[str] = []
        self.warnings: list[str] = []

    def on_think(self, thought: str) -> None:
        self.thoughts.append(thought)
        print(f"\n🧠 [THINK] {thought[:500]}")

    def on_act(self, action: str, params: dict) -> None:
        self.actions.append(action)
        print(f"\n🔧 [ACT] {action}")
        print(f"   参数: {str(params)[:300]}")

    def on_observe(self, observation: str) -> None:
        self.observations.append(observation)
        # 截断长输出
        obs_short = observation[:600] + ("..." if len(observation) > 600 else "")
        print(f"\n👁️  [OBSERVE] {obs_short}")

    def on_warning(self, message: str) -> None:
        self.warnings.append(message)
        print(f"\n⚠️  [WARNING] {message}")

    def on_finish(self, result: str) -> None:
        print(f"\n✅ [FINISH]\n{result[:2000]}")


def main() -> int:
    print("=" * 60)
    print("OmniAgent SmartBench 分析 — 实际引擎测试")
    print("=" * 60)

    # ReAct 引擎，用 deepseek-v4-pro，最大 12 轮
    callback = VerboseCallback()
    engine = ReActEngine(
        model_priority=["deepseek/deepseek-v4-pro"],
        max_iterations=12,
        callback=callback,
    )

    task = (
        "请分析 GitHub 仓库 xianyu-sheng/SmartBench。步骤如下：\n"
        "1. 先执行 git clone https://github.com/xianyu-sheng/SmartBench.git\n"
        "2. 用 list_files 列出 SmartBench 目录结构（多次，探索子目录）\n"
        "3. 用 read_file 读取关键源码文件（README.md, 主要 Python 文件等）\n"
        "4. 用 search_files 搜索关键模式\n"
        "5. 基于实际代码给出完整分析报告，包括：\n"
        "   - 项目用途和定位\n"
        "   - 核心架构和模块\n"
        "   - 技术栈\n"
        "   - 代码质量评估\n"
        "   - 改进建议"
    )

    try:
        result = engine.run(task)
        print(f"\n{'=' * 60}")
        print(f"✅ 执行成功！")
        print(f"{'=' * 60}")
        print(f"\n📊 统计：")
        print(f"   思考次数: {len(callback.thoughts)}")
        print(f"   工具调用: {len(callback.actions)}")
        print(f"   观察次数: {len(callback.observations)}")
        print(f"   警告次数: {len(callback.warnings)}")
        print(f"\n📝 最终结果：\n{result}")
        return 0 if len(callback.actions) > 0 else 1
    except Exception as e:
        print(f"\n❌ 执行失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
