"""验证 PlanExecute 引擎能否正确处理中文路径"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from omniagent.engine.plan_execute_engine import PlanExecuteEngine
from omniagent.engine.callbacks import EngineCallback


def _safe(text: str, max_len: int = 500) -> str:
    """Safe console output: strip non-ASCII emoji and truncate."""
    result = []
    for ch in text[:max_len]:
        try:
            ch.encode("gbk")
            result.append(ch)
        except UnicodeEncodeError:
            result.append("?")
    return "".join(result)


class VerboseCallback(EngineCallback):
    def __init__(self):
        self.thoughts = []
        self.actions = []
        self.observations = []
        self.warnings = []
        self.step_results = []

    def on_think(self, thought: str) -> None:
        self.thoughts.append(thought)
        print(f"\n[T] {_safe(thought, 400)}")

    def on_act(self, action: str, params: dict) -> None:
        self.actions.append((action, params))
        print(f"\n[A] {action}({_safe(str(params), 400)})")

    def on_observe(self, observation: str) -> None:
        self.observations.append(observation)
        obs = _safe(observation, 500)
        if len(observation) > 500:
            obs += "..."
        print(f"[O] {obs}")

    def on_warning(self, message: str) -> None:
        self.warnings.append(message)
        print(f"\n[W] {_safe(message, 400)}")

    def on_step(self, step_id: int, total: int, task: str) -> None:
        print(f"\n[S] Step {step_id}/{total}: {_safe(task, 200)}")

    def on_step_done(self, step_id: int, success: bool, summary: str) -> None:
        status = "OK" if success else "FAIL"
        self.step_results.append((step_id, success, summary))
        print(f"  [{status}] {_safe(summary, 300)}")

    def on_error(self, error: str) -> None:
        print(f"\n[ERR] {_safe(error, 400)}")

    def on_finish(self, result: str) -> None:
        print(f"\n[FINISH] {_safe(result, 2000)}")


def main():
    print("=" * 60)
    print("PlanExecute + 中文路径验证: D:\\语音版的日历工具")
    print("=" * 60)

    callback = VerboseCallback()
    engine = PlanExecuteEngine(
        model_priority=["deepseek/deepseek-v4-pro"],
        max_steps=10,
        callback=callback,
    )

    task = (
        "请分析本地项目 D:\\语音版的日历工具，具体步骤：\n"
        "1. 用 list_files 列出项目目录结构\n"
        "2. 用 read_file 读取关键源文件（基于步骤1的真实输出）\n"
        "3. 给出分析结论：项目用途、技术栈、代码质量、改进建议"
    )

    try:
        result = engine.run(task)
        print(f"\n{'=' * 60}")
        print(f"Done! actions={len(callback.actions)} warnings={len(callback.warnings)} steps={len(callback.step_results)}")
        print(f"{'=' * 60}")
        print(f"\n=== FINAL OUTPUT ===\n{_safe(result, 8000)}")

        # 质量检查
        checks = []
        # 1. 是否有工具执行
        checks.append(("有工具执行", len(callback.actions) > 0))
        # 2. 是否列出了文件（list_files 成功）
        has_list = any(a[0] == "list_files" for a in callback.actions)
        checks.append(("list_files 被调用", has_list))
        # 3. 是否读取了文件
        has_read = any(a[0] == "read_file" for a in callback.actions)
        checks.append(("read_file 被调用", has_read))
        # 4. 结果是否包含实际内容（非空洞）
        has_substance = len(result) > 200 and not result.startswith("继续")
        checks.append(("结果有实质内容", has_substance))
        # 5. 没有参数错误警告
        no_param_err = not any("参数错误" in w for w in callback.warnings)
        checks.append(("无参数验证错误", no_param_err))
        # 6. 没有 NL path 错误
        no_nl_path = not any("自然语言" in w for w in callback.warnings)
        checks.append(("无 NL-path 错误", no_nl_path))

        print("\n=== QUALITY CHECKS ===")
        all_pass = True
        for name, passed in checks:
            status = "PASS" if passed else "FAIL"
            if not passed:
                all_pass = False
            print(f"  [{status}] {name}")

        return 0 if all_pass else 1

    except Exception as e:
        print(f"\nFAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
