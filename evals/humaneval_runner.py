"""
HumanEval benchmark adapter for omniagent.

HumanEval (OpenAI, 2021): 164 Python function-completion tasks.
Metric: pass@k (probability that at least 1 of k samples passes all tests).

Usage:
    python evals/humaneval_runner.py --model deepseek/deepseek-v4-pro --num-tasks 20
    python evals/humaneval_runner.py --model deepseek/deepseek-v4-pro --num-tasks 164
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
    """Build a prompt that asks for ONLY the indented function body."""
    return (
        "Write ONLY the indented body of the following Python function. "
        "Do NOT repeat the def line, docstring, or imports. "
        "Output raw Python code only, no markdown, no explanation.\n\n"
        f"{task['prompt']}"
    )


def extract_code(generated: str, entry_point: str) -> str:
    """Extract ONLY the indented function body from LLM output.

    The HumanEval prompt already contains imports + helper functions +
    function signature + docstring. We need just the indented body
    to append to the prompt.
    """
    # 1) Extract from markdown code block if present
    blocks = list(re.finditer(r"```(?:python)?\s*\n(.*?)```", generated, re.DOTALL))
    for m in reversed(blocks):
        block = m.group(1)
        if f"def {entry_point}" in block or "    " in block[:40]:
            generated = block
            break

    # 2) Find the function body: lines AFTER the def line and docstring
    lines = generated.split("\n")
    body_start = 0
    in_docstring = False

    for i, line in enumerate(lines):
        s = line.strip()

        # Skip the def line
        if s.startswith(f"def {entry_point}"):
            continue

        # Handle docstrings
        if s.startswith('"""') or s.startswith("'''"):
            if not in_docstring:
                in_docstring = True
                dq = s[:3]
                if s.count(dq) >= 2 and len(s) > 3:  # single-line docstring
                    in_docstring = False
                continue
            else:
                in_docstring = False
                continue
        if in_docstring:
            continue

        # This is the first body line
        if s and not s.startswith("```") and not s.startswith("Here"):
            body_start = i
            break
        body_start = i + 1

    body_lines = lines[body_start:]

    # 3) Trim trailing noise
    while body_lines and (
        not body_lines[-1].strip()
        or body_lines[-1].strip().startswith("```")
        or body_lines[-1].strip().startswith("Here")
    ):
        body_lines.pop()

    return "\n".join(body_lines)


def evaluate_task(task: dict[str, Any], completion: str) -> dict[str, Any]:
    """Evaluate a HumanEval task.

    The prompt contains imports + helper functions + function signature.
    The completion is just the indented body.
    Full code = prompt + body + test + check().
    """
    full_code = (
        task["prompt"] + "\n"
        + completion + "\n\n"
        + task["test"] + "\n\n"
        + f"check({task['entry_point']})\n"
    )

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
                samples.append({
                    "task_id": task_id,
                    "passed": False,
                    "error": f"API: {e}",
                })

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
            "error": samples[0].get("error") if not any_passed else None,
        })

    return results


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if r["pass_at_k"])
    return {
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
