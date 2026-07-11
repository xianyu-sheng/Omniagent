"""
HumanEval 评测适配器 — 将 omniagent 的多模型路由接到 HumanEval 基准。

HumanEval（OpenAI, 2021）是衡量 LLM 代码生成能力的标准基准：
- 164 道 Python 函数补全题
- 每道题包含函数签名 + docstring + 测试用例
- 评估指标：pass@k（k 次采样中至少一次通过测试的概率）

用法：
    python evals/humaneval_runner.py --model deepseek/deepseek-v4-pro --num-tasks 20
    python evals/humaneval_runner.py --model deepseek/deepseek-v4-pro --num-tasks 164 --num-samples 3
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

_DATASET_PATH = Path("/tmp/HumanEval.jsonl")


def load_tasks(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or _DATASET_PATH
    tasks = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                tasks.append(json.loads(line))
    return tasks


def build_prompt(task: dict[str, Any]) -> str:
    return (
        "You are a Python code generator. Output ONLY executable Python code, "
        "no explanation, no markdown fences, no conversation.\n\n"
        f"{task['prompt']}"
    )


def extract_code(generated: str, entry_point: str) -> str:
    # 1) Try to find a markdown code block — take the LAST one containing the entry point
    blocks = list(re.finditer(r"```(?:python)?\s*\n(.*?)```", generated, re.DOTALL))
    for m in reversed(blocks):
        block = m.group(1)
        if f"def {entry_point}" in block:
            generated = block
            break

    # 2) Find the function definition and take everything from there
    sig_pattern = rf"def\s+{re.escape(entry_point)}\s*\("
    match = re.search(sig_pattern, generated)
    if match:
        generated = generated[match.start():]

    # 3) Trim trailing non-code (anything after the last meaningful line)
    lines = generated.split("\n")
    # Find last line that looks like code (not blank, not a comment-only, not a markdown fence)
    while lines and (
        not lines[-1].strip()
        or lines[-1].strip().startswith("```")
        or lines[-1].strip().startswith("Here")
    ):
        lines.pop()
    generated = "\n".join(lines)

    return generated.strip()


def evaluate_task(task: dict[str, Any], completion: str) -> dict[str, Any]:
    full_code = completion + "\n\n" + task["test"] + "\n\n"
    full_code += f"check({task['entry_point']})\n"

    result = {"task_id": task["task_id"], "passed": False, "error": None}
    namespace: dict[str, Any] = {}
    try:
        exec(full_code, namespace)
        result["passed"] = True
    except AssertionError:
        result["error"] = "AssertionError"
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"

    return result


def run_humaneval(
    model: str = "deepseek/deepseek-v4-pro",
    num_tasks: int = 20,
    num_samples: int = 1,
    dataset_path: Path | None = None,
) -> list[dict[str, Any]]:
    from omniagent.utils.llm_client import chat_completion

    tasks = load_tasks(dataset_path)[:num_tasks]
    results = []

    for i, task in enumerate(tasks):
        task_id = task["task_id"]
        prompt = build_prompt(task)
        print(f"[{i+1}/{num_tasks}] {task_id} ...", end=" ", flush=True)

        samples = []
        for _ in range(num_samples):
            try:
                for v in list(os.environ.keys()):
                    if "proxy" in v.lower():
                        os.environ.pop(v, None)

                response = chat_completion(
                    model_id=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0 if num_samples == 1 else 0.8,
                    max_tokens=1024,
                )
                completion = extract_code(response, task["entry_point"])
                eval_result = evaluate_task(task, completion)
                samples.append(eval_result)
                if eval_result["passed"]:
                    break
            except Exception as e:
                samples.append({"task_id": task_id, "passed": False, "error": str(e)})

        any_passed = any(s["passed"] for s in samples)
        status = "PASS" if any_passed else "FAIL"
        err = samples[0].get("error", "")
        detail = f"({err})" if err and not any_passed else ""
        print(f"{status} {detail}")

        results.append({
            "task_id": task_id,
            "passed": samples[0]["passed"] if samples else False,
            "pass_at_k": any_passed,
            "samples": len(samples),
        })

    return results


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if r["pass_at_k"])
    return {
        "model": results[0].get("model", "unknown") if results else "unknown",
        "total": total,
        "passed": passed,
        "pass_rate": f"{passed}/{total} ({passed/total*100:.1f}%)" if total else "N/A",
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="HumanEval benchmark for omniagent")
    p.add_argument("--model", default="deepseek/deepseek-v4-pro")
    p.add_argument("--num-tasks", type=int, default=20)
    p.add_argument("--num-samples", type=int, default=1)
    p.add_argument("--output", default="/tmp/humaneval_report.json")
    args = p.parse_args(argv)

    print(f"HumanEval via omniagent")
    print(f"  Model:  {args.model}")
    print(f"  Tasks:  {args.num_tasks}")
    print(f"  Pass@k: k={args.num_samples}")
    print()

    results = run_humaneval(
        model=args.model,
        num_tasks=args.num_tasks,
        num_samples=args.num_samples,
    )

    summary = summarize(results)
    print(f"\n{'='*50}")
    print(f"Result: {summary['pass_rate']}")
    print(f"{'='*50}")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"Report: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
