"""
Combined Engines — 思考范式组合引擎。

将多种思考范式组合使用，发挥各自优势：
- PlanReactEngine: 全局规划 + 每步 ReAct 执行
- PlanReflectionEngine: 规划执行 + 反思修正
- ReactReflectionEngine: ReAct 探索 + 反思审查
"""

from __future__ import annotations

import logging
from typing import Any

from omniagent.engine.context import AgentContext
from omniagent.engine.plan_execute_engine import PlanExecuteEngine
from omniagent.engine.react_engine import ReActEngine, BUILTIN_TOOLS
from omniagent.engine.reflection_engine import ReflectionEngine
from omniagent.utils.llm_client import chat_completion

logger = logging.getLogger(__name__)


class PlanReactEngine:
    """
    Plan + React 组合引擎。

    策略：用 Plan-Execute 做全局规划，每个步骤用 ReAct 循环执行。
    适合需要既有宏观规划、又有灵活工具调用的复杂任务。
    """

    def __init__(
        self,
        model_priority: list[str],
        *,
        max_steps: int = 15,
        react_iterations: int = 5,
    ) -> None:
        self.model_priority = model_priority
        self.max_steps = max_steps
        self.react_iterations = react_iterations
        self.planner = PlanExecuteEngine(model_priority, max_steps=max_steps)
        self.reactor = ReActEngine(model_priority, max_iterations=react_iterations)

    def run(self, user_input: str, context: AgentContext | None = None) -> str:
        ctx = context or AgentContext()

        # Phase 1: 全局规划
        logger.info("PlanReact Phase 1: 全局规划")
        plan = self.planner._plan(user_input)
        steps = plan.get("steps", [])

        if not steps:
            return plan.get("analysis", "未能生成有效的执行计划。")

        logger.info(f"PlanReact: 生成 {len(steps)} 个步骤")

        # Phase 2: 每步用 ReAct 执行
        logger.info("PlanReact Phase 2: ReAct 逐步执行")
        results = []

        for i, step in enumerate(steps[:self.max_steps]):
            step_task = step.get("task", "")
            step_id = step.get("id", i + 1)

            logger.info(f"PlanReact 步骤 {step_id}: {step_task}")

            # 构建包含全局上下文的 ReAct 输入
            prev_context = ""
            if results:
                prev_context = "\n之前步骤的结果:\n" + "\n".join(
                    f"- 步骤 {r['step_id']}: {r['result'][:150]}"
                    for r in results[-3:]
                )

            react_input = (
                f"全局任务: {user_input}\n"
                f"当前步骤 ({step_id}/{len(steps)}): {step_task}"
                f"{prev_context}"
            )

            # 用 ReAct 执行当前步骤
            try:
                step_result = self.reactor.run(react_input, context=ctx)
            except Exception as e:
                step_result = f"步骤执行失败: {e}"

            results.append({
                "step_id": step_id,
                "task": step_task,
                "result": step_result,
            })

            # 存入上下文
            ctx.set(f"step_{step_id}_result", step_result)

        # Phase 3: 汇总
        logger.info("PlanReact Phase 3: 汇总结果")
        summary = self._summarize(user_input, results)
        return summary

    def _summarize(self, user_input: str, results: list[dict]) -> str:
        """汇总所有步骤的结果。"""
        results_text = "\n\n".join(
            f"## 步骤 {r['step_id']}: {r['task']}\n{r['result']}"
            for r in results
        )

        messages = [
            {"role": "system", "content": "你是一个任务汇总专家。请根据各步骤的执行结果，给出最终的完整回答。整合所有步骤的输出，形成连贯的结论。"},
            {"role": "user", "content": f"原始任务: {user_input}\n\n各步骤执行结果:\n{results_text}"},
        ]

        try:
            for model_id in self.model_priority:
                try:
                    return chat_completion(model_id, messages, max_tokens=4096, temperature=0.5)
                except Exception:
                    continue
            return results_text
        except Exception:
            return results_text


class PlanReflectionEngine:
    """
    Plan + Reflection 组合引擎。

    策略：用 Plan-Execute 做规划和执行，最后用 Reflection 审查和修正输出质量。
    适合需要高质量最终输出的任务。
    """

    def __init__(
        self,
        model_priority: list[str],
        *,
        max_steps: int = 15,
        review_rounds: int = 2,
        pass_threshold: int = 7,
    ) -> None:
        self.model_priority = model_priority
        self.max_steps = max_steps
        self.review_rounds = review_rounds
        self.pass_threshold = pass_threshold
        self.planner = PlanExecuteEngine(model_priority, max_steps=max_steps)
        self.reflector = ReflectionEngine(
            model_priority,
            max_rounds=review_rounds,
            pass_threshold=pass_threshold,
        )

    def run(self, user_input: str, context: AgentContext | None = None) -> str:
        ctx = context or AgentContext()

        # Phase 1: Plan-Execute 执行
        logger.info("PlanReflection Phase 1: 规划并执行")
        initial_output = self.planner.run(user_input, context=ctx)

        # Phase 2: Reflection 审查和修正
        logger.info("PlanReflection Phase 2: 反思审查")
        try:
            final_output = self.reflector.run(
                f"原始任务: {user_input}\n\n执行结果:\n{initial_output}"
            )
        except Exception as e:
            logger.warning(f"Reflection 阶段失败: {e}")
            final_output = initial_output

        return final_output


class ReactReflectionEngine:
    """
    ReAct + Reflection 组合引擎。

    策略：用 ReAct 进行探索和执行，最后用 Reflection 审查输出质量。
    适合需要工具探索且要求高质量输出的任务。
    """

    def __init__(
        self,
        model_priority: list[str],
        *,
        react_iterations: int = 8,
        review_rounds: int = 2,
        pass_threshold: int = 7,
    ) -> None:
        self.model_priority = model_priority
        self.react_iterations = react_iterations
        self.review_rounds = review_rounds
        self.pass_threshold = pass_threshold
        self.reactor = ReActEngine(model_priority, max_iterations=react_iterations)
        self.reflector = ReflectionEngine(
            model_priority,
            max_rounds=review_rounds,
            pass_threshold=pass_threshold,
        )

    def run(self, user_input: str, context: AgentContext | None = None) -> str:
        ctx = context or AgentContext()

        # Phase 1: ReAct 探索和执行
        logger.info("ReactReflection Phase 1: ReAct 探索执行")
        initial_output = self.reactor.run(user_input, context=ctx)

        # Phase 2: Reflection 审查和修正
        logger.info("ReactReflection Phase 2: 反思审查")
        try:
            final_output = self.reflector.run(
                f"原始任务: {user_input}\n\n执行结果:\n{initial_output}"
            )
        except Exception as e:
            logger.warning(f"Reflection 阶段失败: {e}")
            final_output = initial_output

        return final_output
