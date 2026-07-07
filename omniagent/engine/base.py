"""BaseEngine — 引擎抽象基类（R2）。

抽取公共属性与 ``_call_llm``，消除 react/plan/reflection/novel 四份
``_call_llm`` 复制及参数漂移：

- ``max_tokens`` 硬编码 131072 vs 8192（B4 已修，此处统一来源）；
- ``temperature`` 0.3 vs 0.8 散落各处；
- B7 的 per-model ``api_key``/``base_url`` 覆盖在 novel 中未生效（漂移 bug）。

子类只需实现 ``run`` 与自身特有参数（``max_iterations``/``max_steps``/
``max_rounds`` 等），公共 LLM 调用与多模型 fallback 由本基类提供。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import httpx

from omniagent.engine.callbacks import EngineCallback
from omniagent.engine.context import AgentContext
from omniagent.utils.llm_client import ResponseTruncatedError, chat_completion

if TYPE_CHECKING:
    from omniagent.engine.budget import BudgetManager
    from omniagent.engine.tool_tracker import ToolExecutionTracker

logger = logging.getLogger(__name__)


class BaseEngine(ABC):
    """所有引擎的公共基类。"""

    # observation 截断阈值（子类可覆盖）；统一可配，替代各处硬编码 2000。
    observation_truncate: int = 2000

    def __init__(
        self,
        model_priority: list[str],
        *,
        callback: EngineCallback | None = None,
        model_configs: dict[str, Any] | None = None,
        temperature: float = 0.3,
    ) -> None:
        self.model_priority = list(model_priority)
        self.callback = callback or EngineCallback()
        # alias -> ModelConfig，供 _call_llm 读每模型 max_tokens/api_key/base_url（B4/B7）
        self.model_configs = model_configs or {}
        self.temperature = temperature
        # F6: 协作式中断标志，外部调 interrupt() 后 run() 在下一轮退出
        self._interrupted: bool = False
        # F4: 本次 run 注入的 ContextManager（run 起点设置，供 _history_messages 消费）
        self._ctx_mgr: Any = None

    def interrupt(self) -> None:
        """F6: 协作式中断——外部调用后，run() 在下一轮迭代顶部退出。"""
        self._interrupted = True

    def _reset_interrupt(self) -> None:
        """每轮 run() 开头重置中断标志。"""
        self._interrupted = False

    def _context_window(self) -> int:
        """当前激活模型的上下文窗口（取最小=瓶颈模型）；未知则 128000。"""
        windows = [
            getattr(mc, "context_window", 0)
            for mc in self.model_configs.values()
            if getattr(mc, "context_window", 0) > 0
        ]
        return min(windows) if windows else 128000

    def _near_context_window(self, messages: list[dict[str, str]], ratio: float = 0.8) -> bool:
        """F6: 估算 messages token 是否接近上下文窗口（默认 80%）。

        粗估（字符数//2）仅用于预算预警/拒绝大 observation，非精确计费。
        """
        window = self._context_window()
        if window <= 0:
            return False
        est = sum(len(m.get("content", "")) for m in messages) // 2
        return est > ratio * window

    def _history_messages(self, context: Any) -> list[dict[str, str]]:
        """F4: 优先消费注入的 ctx_mgr（已压缩）消息，否则回退 AgentContext 历史。

        返回非 system 消息（system 由各引擎自行注入自己的 system_prompt）。
        """
        if self._ctx_mgr is not None:
            return [m for m in self._ctx_mgr.get_messages() if m.get("role") != "system"]
        if context:
            return context.get_conversation_messages()
        return []

    def _maybe_compact_messages(
        self,
        messages: list[dict[str, str]],
        turn: int,
        every: int = 5,
    ) -> list[dict[str, str]]:
        """F4: 每 ``every`` 轮压缩 in-run messages，复用 ContextManager 的 F3 压缩逻辑。

        引擎局部 ``messages`` 在迭代中 O(n) 增长，每轮重发给 LLM 造成 O(n²) token
        成本（§8.9.6）。每 5 轮用临时 ContextManager 跑一次 F3 compact（6 段/安全
        截断），把早期轨迹摘要化、保留近期上下文。无 model_priority 或 LLM 失败时
        自动回退正则摘要（F3 已实现）。
        """
        if turn <= 0 or turn % every != 0:
            return messages
        try:
            from omniagent.repl.context_manager import ContextManager

            tmp = ContextManager(max_tokens=self._context_window())
            for m in messages:
                tmp.add_message(m.get("role", "user"), m.get("content", ""))
            tmp.compact(model_priority=self.model_priority or None)
            compacted = tmp.get_messages()
            return compacted if compacted else messages
        except Exception as e:  # noqa: BLE001 — 压缩绝不能中断主循环
            logger.warning(f"in-run 压缩失败（已忽略，沿用原 messages）: {e}")
            return messages

    def _call_llm(self, messages: list[dict[str, str]], max_tokens: int | None = None) -> str:
        """调用 LLM，支持多模型 fallback。

        ``max_tokens`` 优先级：显式入参 > ``ModelConfig.max_tokens`` > 8192 默认；
        ``chat_completion`` 再按厂商上限钳制（B4）。``api_key``/``base_url`` 按
        模型覆盖（B7）。温度取 ``self.temperature``（novel=0.8，其余=0.3）。

        错误分流（R1 / Q9）：
        - 401/403（认证失败）、400（请求被拒）= **终端错误**，切模型无意义，
          立即上抛并 ``callback.on_error``，避免用坏 Key 逐一慢试全部模型；
        - 429/5xx/网络错误/响应截断 = **瞬时错误**，切下一个模型；
        - 全部模型失败 → ``callback.on_error`` + 抛 RuntimeError。
        """
        last_error: Exception | None = None
        for model_id in self.model_priority:
            try:
                mc = self.model_configs.get(model_id)
                mt = max_tokens or getattr(mc, "max_tokens", None) or 8192
                creds = None
                base = None
                if mc:
                    base = getattr(mc, "base_url", "") or None
                    mk = getattr(mc, "api_key", "") or ""
                    if mk and "/" in model_id:
                        creds = {model_id.split("/", 1)[0].lower(): mk}
                return chat_completion(
                    model_id, messages, max_tokens=mt,
                    temperature=self.temperature, credentials=creds, base_url=base,
                )
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                if status in (401, 403):
                    self.callback.on_error(
                        f"模型 {model_id} 认证失败 ({status})，请检查 API Key")
                    raise RuntimeError(
                        f"模型 {model_id} 认证失败 ({status})，请检查 API Key") from e
                if status == 400:
                    self.callback.on_error(f"模型 {model_id} 请求被拒 (400): {e}")
                    raise RuntimeError(
                        f"模型 {model_id} 请求被拒 (400)，请检查参数/模型名") from e
                # 429/5xx/其他 HTTP：瞬时，切下一个模型
                last_error = e
                logger.warning(f"模型 {model_id} HTTP {status} 失败: {e}，尝试下一个...")
            except (
                httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout,
                httpx.RemoteProtocolError, httpx.WriteError, httpx.PoolTimeout,
            ) as e:
                last_error = e
                logger.warning(f"模型 {model_id} 网络错误 ({type(e).__name__}): {e}，尝试下一个...")
            except ResponseTruncatedError as e:
                last_error = e
                logger.warning(f"模型 {model_id} 响应截断: {e}，尝试下一个...")
            except Exception as e:
                last_error = e
                logger.warning(f"模型 {model_id} 失败: {e}，尝试下一个...")
        self.callback.on_error(f"所有模型均调用失败: {last_error}")
        raise RuntimeError(f"所有模型均调用失败: {last_error}")

    # ── F2: 合成提示注入 ─────────────────────────────────────

    def _inject_synthesis_prompt(
        self,
        budget: BudgetManager,
        tracker: ToolExecutionTracker | None,
    ) -> tuple[str, str] | None:
        """F2: 按剩余预算/工具调用/阶段选择合成提示场景（6 场景）。

        返回 ``(scenario, prompt)`` 或 ``None``（无需注入）。调用方把 ``prompt``
        作为 user 消息追加进 ``messages``，引导 LLM 在当前阶段做正确的事。

        场景优先级：
        1. **force_synthesis**：剩余预算 <15% 且有工具调用 → 必须立即合成最终答案；
        2. （刚奖励过空洞补救 → 跳过，hint 已注入，避免连续 user 消息堆叠）；
        3. **converge_synthesis**：收束阶段且有工具调用 → 准备收尾合成；
        4. **soft_warning**：收束阶段但 0 工具调用 → 立即行动或基于已知回答；
        5. **compression_reward**：刚触发压缩奖励 → 鼓励继续产出；
        6. **progress_expansion**：中段执行且最近成功 → 进展良好继续；
        7. **gentle_hint**：探索阶段且 0 工具调用 → 2-3 步后开始执行。
        """
        tool_calls = len(tracker.calls) if tracker else 0
        last_success = bool(tracker and tracker.calls and tracker.calls[-1].success)
        total = budget.total if budget.total > 0 else 1
        remaining_ratio = budget.remaining / total

        # 1. 强制合成：预算将尽且做过工
        if remaining_ratio < 0.15 and tool_calls >= 1:
            return (
                "force_synthesis",
                f"⚠️ 预算仅剩 {budget.remaining}/{budget.total} 轮，你已执行 {tool_calls} 次工具。"
                "必须在本轮直接给出 final_answer——基于已执行的工具结果合成最终回答，"
                "不要再调用工具，直接总结产物（文件路径/代码/命令输出）。",
            )

        # 2. 刚奖励过空洞补救：hint 已作为上一条 user 消息注入，跳过避免堆叠
        if budget.rewards and budget.rewards[-1][0] == "hollow":
            return None

        # 3. 收束阶段且有工具：准备合成
        if budget.is_converge_phase() and tool_calls >= 1:
            return (
                "converge_synthesis",
                f"ℹ️ 已进入收束阶段（{budget.summary()}），已执行 {tool_calls} 次工具。"
                "请停止探索，基于已有结果整理 final_answer，附上产物路径/代码/命令输出。",
            )

        # 4. 收束阶段但没工具：立即行动
        if budget.is_converge_phase() and tool_calls == 0:
            return (
                "soft_warning",
                "⚠️ 已进入收束阶段但未调用任何工具。请立即调用工具执行，"
                "或基于已知信息直接给出 final_answer，不要再探索。",
            )

        # 5. 压缩奖励：鼓励继续
        if budget.rewards and budget.rewards[-1][0] == "compression":
            n = budget.rewards[-1][1]
            return (
                "compression_reward",
                f"ℹ️ 上下文已压缩，奖励 +{n} 轮预算。把省下的预算用在产出上，继续执行剩余任务。",
            )

        # 6. 中段执行良好：鼓励
        if budget.is_execute_phase() and tool_calls >= 3 and last_success:
            return (
                "progress_expansion",
                f"✓ 进展良好（{tool_calls} 次工具，最近一次成功）。"
                "继续执行剩余步骤，完成后给出 final_answer。",
            )

        # 7. 探索阶段无工具：温和提示
        if budget.is_explore_phase() and tool_calls == 0:
            return (
                "gentle_hint",
                "ℹ️ 当前为探索阶段。建议 2-3 步了解结构后立即开始执行（write_file/command），"
                "不要无限探索。",
            )

        return None

    # ── F2: mercy compile / exhaustion report ────────────────

    def _synthesis_prompt(self, user_input: str, tracker: ToolExecutionTracker) -> str:
        """构造 mercy compile 的无格式约束合成 prompt。"""
        return (
            "你是一个 Agent 的收尾合成器。Agent 已执行若干工具但未在预算内给出最终答案。\n"
            f"用户原始需求：{user_input}\n\n"
            f"已执行工具记录：\n{tracker.detail_log()}\n\n"
            "请基于以上工具执行结果，直接给出最终回答——给用户看的自然语言总结，"
            "附上产物路径/代码/命令输出。不要输出 JSON，不要 ReAct 格式，直接回答。"
        )

    def _exhaustion_report(self, user_input: str, tracker: ToolExecutionTracker) -> str:
        """F2: 从 tracker.calls 程序化拼出结构化报告（成功/失败/参数/最多 10 条）。"""
        lines = [
            f"⚠️ 达到最大迭代次数，以下是已执行工具的结构化报告：",
            "",
            f"**用户需求**：{user_input}",
            "",
            f"**执行摘要**：{tracker.execution_summary()}",
            "",
            f"**详细记录**（最多 10 条）：",
        ]
        for i, call in enumerate(tracker.calls[-10:], 1):
            status = "✓ 成功" if call.success else "✗ 失败"
            params = call.params or {}
            lines.append(f"{i}. {status} {call.tool_name}({params})")
            if call.result_summary:
                lines.append(f"   结果：{call.result_summary}")
            if call.error:
                lines.append(f"   错误：{call.error}")
        lines.append("")
        lines.append("请基于以上执行结果判断任务完成度，或重新发起更具体的指令。")
        return "\n".join(lines)

    def _mercy_compile(
        self,
        user_input: str,
        tracker: ToolExecutionTracker | None,
        messages: list[dict[str, str]],
    ) -> str:
        """F2: 迭代耗尽时的优雅降级链（mercy compile → exhaustion report → 报错）。

        ① 换备选模型做一次**无 ReAct 格式约束**的合成（仅当有工具执行数据）；
        ② 合成失败/无数据则从 ``tracker.calls`` 程序化拼出结构化报告；
        ③ 连工具数据都没有才报错。

        避免 §8.x 的"一次瞬时 API 故障直接杀掉整个运行"——``tracker.calls`` 数据
        在手却未用，这里把它变成可用的部分结果。
        """
        # ① 备选模型合成（有工具数据才值得合成）
        if tracker and tracker.has_executions():
            try:
                answer = self._call_llm([
                    {"role": "system",
                     "content": "你是 Agent 的收尾合成器，直接输出最终回答，不要 JSON/ReAct 格式。"},
                    {"role": "user", "content": self._synthesis_prompt(user_input, tracker)},
                ])
                if answer and answer.strip():
                    self.callback.on_warning("迭代耗尽，已用 LLM 合成最终回答（mercy compile）")
                    return answer.strip()
            except Exception as e:  # noqa: BLE001 — 合成失败回退报告，不抛
                logger.warning(f"mercy compile 合成失败，回退结构化报告: {e}")
            # ② 结构化报告
            self.callback.on_warning("迭代耗尽，已生成结构化执行报告（exhaustion report）")
            return self._exhaustion_report(user_input, tracker)

        # ③ 无数据
        self.callback.on_error("迭代耗尽且无工具执行数据，无法合成结果")
        max_iter = getattr(self, "max_iterations", None)
        budget_str = f" ({max_iter}) " if max_iter else " "
        return (
            f"达到最大迭代次数{budget_str}未能得出最终答案，"
            "且未执行任何工具调用。请尝试简化问题或使用更具体的指令。"
        )

    @abstractmethod
    def run(self, user_input: str, context: AgentContext | None = None) -> str:
        """子类实现主循环。"""
        raise NotImplementedError
