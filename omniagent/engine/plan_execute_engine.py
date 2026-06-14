"""
Plan-Execute Engine — 规划-执行两阶段引擎。

Phase 1: Planning — LLM 生成步骤列表
Phase 2: Execution — 逐步执行，每步结果写入 context
"""

from __future__ import annotations

import logging
from typing import Any

from omniagent.engine.callbacks import EngineCallback
from omniagent.engine.context import AgentContext
from omniagent.engine.react_engine import _check_hollow_answer
from omniagent.engine.tool_tracker import ToolExecutionTracker
from omniagent.nodes.tool_node import ToolNode
from omniagent.utils.llm_client import chat_completion
from omniagent.utils.response_adapter import parse_plan, parse_react

logger = logging.getLogger(__name__)

PLAN_SYSTEM_PROMPT = """你是一个任务规划专家。将用户任务分解为可执行的原子步骤。

## 🔴 核心原则

1. **先探查再规划** — 如果任务涉及已有文件或项目，第一步必须是 list_files 了解现有结构
2. **路径必须是实际的本地路径** — file_path 必须是具体的文件系统路径，如 `D:/project/app.py` 或 `src/main.py`。**绝对禁止**将自然语言描述作为路径值（如"基于步骤1的输出"、"来自上一步的文件列表"等）
3. **路径来自 list_files** — 任何 read_file/write_file/edit_file 的 file_path 必须直接来自 list_files 返回的真实文件名
4. **读取文件用 read_file，不要用 command** — read_file 是读取文件内容的专用工具，command 用于执行脚本/安装依赖，不要用 `Get-Content` 或 `cat` 等命令替代 read_file
5. **参数名必须使用标准名称** — file_path（不是 path）、action（不是 command）、content（不是 text）
6. **tool 字段必须是下方列表中的精确工具名** — 严禁发明或猜测工具名
7. **不需要工具的步骤** — tool 设为 null，如"汇总分析结果"、"输出最终结论"
8. **每步只做一个原子操作** — 不要把"创建5个文件"写成一个步骤，拆成5个步骤；不要把"读取所有文件"写成一个步骤，每个关键文件单独一个 read_file 步骤

## 输出格式

只输出一个 JSON，不要输出其他任何内容：
```json
{{"analysis":"简要分析任务目标和策略","steps":[{{"id":1,"task":"步骤描述","tool":"工具名或null","params":{{"参数名":"值"}}}}]}}
```

## ⚠️ 可用工具列表（完整且唯一）

以下是所有可用工具，不存在其他工具。tool 字段必须是下列之一或 null：

- command: {{"action": "终端命令"}} — 在本机终端执行 shell 命令（Windows 用 PowerShell）。用于 git clone、安装依赖、运行脚本等。
- read_file: {{"file_path": "路径", "start_line": "起始行号(可选,从1开始)", "max_lines": "读取行数(可选)"}} — 读取本机文件内容。⚠️ 路径必须来自 list_files 的实际输出。
- write_file: {{"file_path": "路径", "content": "内容"}} — 将内容写入本机文件（覆盖）。自动创建父目录。
- list_files: {{"file_path": "目录", "pattern": "*.py"}} — 列出本机目录文件。⚠️ 读取任何文件前必须先执行此步骤。
- search_files: {{"file_path": "目录", "search_pattern": "关键词"}} — 在本机文件中搜索关键词（类似 grep）。
- git: {{"git_command": "status|diff|log|add|commit"}} — 本机 Git 操作。
- web_fetch: {{"url": "完整URL"}} — HTTP GET 抓取任意 URL 内容。
- github_fetch: {{"repo": "owner/repo", "github_action": "list_files|fetch_file|fetch_readme", "github_path": "文件路径(fetch_file用)", "branch": "main"}} — GitHub 仓库专用操作。仅支持公开仓库。
- edit_file: {{"file_path": "路径", "old_text": "原文（必须精确匹配）", "new_text": "新文"}} — 精确查找替换编辑本机文件。
- create_directory: {{"file_path": "目录路径"}} — 创建目录（自动递归创建父目录）。
- file_move: {{"source": "源文件路径", "destination": "目标路径"}} — 移动文件或文件夹到新位置。
- file_copy: {{"source": "源文件路径", "destination": "目标路径"}} — 复制文件到新位置。
- batch_write: {{"files": [{{"path": "a.py", "content": "..."}}, ...]}} — 原子性批量写入多个文件。
- batch_edit: {{"edits": [{{"file_path": "a.py", "old_text": "...", "new_text": "..."}}, ...]}} — 批量编辑多个文件。
- code_index: {{"search_pattern": "符号名", "file_path": "目录"}} — 基于 AST 搜索 Python 代码符号。
- ast_analyze: {{"file_path": "Python文件"}} — AST 深度分析 Python 文件。
- refactor: {{"refactor_action": "rename|clean_imports|analyze", "old_name": "旧名", "new_name": "新名", "file_path": "路径"}} — 代码重构。
- diff_preview: {{"file_path": "路径", "old_text": "原文", "new_text": "新文"}} — 预览修改 diff（不实际改文件）。
- mcp_call: {{"tool_name": "server:tool", "tool_args": {{}}}} — 调用 MCP 外部工具服务器。

## 分析代码仓库的标准规划

### 重要：用户输入中会包含项目的**真实文件列表**（系统已自动执行 list_files）。
请直接使用这些真实文件路径来规划 read_file 步骤，不要猜测文件名。

### ✅ 正确示例（基于真实文件列表）

假设用户输入包含：
```
根目录文件: D:/myproject/app.py, D:/myproject/requirements.txt, D:/myproject/src/main.py
```

则规划如下（使用真实路径）：
```json
{"analysis":"分析项目结构和代码质量","steps":[
  {"id":1,"task":"读取 README.md 了解项目","tool":"read_file","params":{"file_path":"D:/myproject/README.md"}},
  {"id":2,"task":"读取依赖配置 requirements.txt","tool":"read_file","params":{"file_path":"D:/myproject/requirements.txt"}},
  {"id":3,"task":"读取入口文件 app.py","tool":"read_file","params":{"file_path":"D:/myproject/app.py"}},
  {"id":4,"task":"读取核心模块 src/main.py","tool":"read_file","params":{"file_path":"D:/myproject/src/main.py"}},
  {"id":5,"task":"基于实际代码汇总分析结果","tool":null,"params":{}}
]}
```

### ❌ 绝对禁止
- 编造不在文件列表中的文件名
- 使用自然语言描述代替实际路径
- 规划少于 5 个步骤（分析任务必须充分探索）

## 运行环境

- Windows 使用 PowerShell 命令（如 Get-ChildItem、Move-Item、Copy-Item），不要用 Linux 命令（ls、cat、mkdir -p）
- 执行命令前注意当前工作目录
"""

# ── 参数验证：防止 LLM 将自然语言填入文件路径 ──
_NL_PATH_PATTERNS = [
    # 中文自然语言描述冒充路径
    r"基于步骤[一二三\d]+的(输出|结果)",
    r"根据.*步骤.*(输出|结果|文件)",
    r"来自.*(步骤|上一步|list_files).*(输出|结果)",
    r"从.*输出.*(获取|选择|读取)",
    r"上一?步.*(输出|结果|文件)",
    r"^\s*(步骤|根据|来自|基于|使用|参考|见|参见).*",
    # 问句/指令
    r"[?？]",
    r"^(请|需要|应该|可以|必须|可能|尝试|确认)",
]


def _validate_tool_params(tool: str, params: dict) -> dict:
    """验证工具参数，特别拦截将自然语言填入路径参数的情况。

    Returns:
        {"valid": bool, "reason": str}
    """
    if not params:
        return {"valid": True, "reason": ""}

    # 只验证文件相关工具
    path_tools = {
        "read_file", "write_file", "edit_file", "list_files",
        "create_directory", "file_move", "file_copy",
        "ast_analyze", "refactor", "diff_preview",
    }
    if tool not in path_tools:
        return {"valid": True, "reason": ""}

    # 检查所有路径类参数
    path_params = {"file_path", "path", "source", "destination"}
    for key in path_params & set(params.keys()):
        value = str(params[key]).strip()
        if not value:
            continue

        # 1. 长度检测：正常路径很少超过 200 字符
        if len(value) > 200:
            return {
                "valid": False,
                "reason": f"参数 '{key}' 的值过长({len(value)}字符)，不像合法的文件路径: {value[:100]}...",
            }

        # 2. 自然语言模式检测
        import re
        for pattern in _NL_PATH_PATTERNS:
            if re.search(pattern, value):
                return {
                    "valid": False,
                    "reason": f"参数 '{key}' 的值是自然语言描述而非实际路径: '{value[:80]}'。请使用 list_files 输出的真实文件路径。",
                }

        # 3. 中文字符检测 — 需区分真实中文路径和 NL 描述
        cjk_count = sum(1 for c in value if '一' <= c <= '鿿')
        if cjk_count > 5:
            # 先判断是否"看起来像真实路径"（有盘符/斜杠/扩展名等结构特征）
            looks_like_path = _looks_like_filesystem_path(value)
            if not looks_like_path:
                # 既有很多中文又没有路径结构 → 很可能是 NL 描述
                return {
                    "valid": False,
                    "reason": (
                        f"参数 '{key}' 包含 {cjk_count} 个中文字符且没有路径结构特征: "
                        f"'{value[:80]}'。这看起来是自然语言而非文件路径。"
                        f"请使用 list_files 输出的实际文件路径。"
                    ),
                }

    return {"valid": True, "reason": ""}


def _looks_like_filesystem_path(value: str) -> bool:
    """判断一个字符串是否'看起来像'文件系统路径（而非自然语言描述）。

    检查项（满足任一即返回 True）：
    - Windows 盘符开头: C:\\, D:/ 等
    - Unix 绝对路径: /home/...
    - 相对路径: .\\, ..\\, ./
    - 含有路径分隔符 + 文件扩展名
    - 路径在磁盘上真实存在
    """
    import os
    import re

    # 1. Windows 盘符: C:\... 或 D:/...
    if re.match(r'^[A-Za-z]:[\\/]', value):
        return True

    # 2. Unix 绝对路径
    if value.startswith('/'):
        return True

    # 3. 相对路径标记
    if value.startswith(('.\\', '..\\', './', '../')):
        return True

    # 4. 含有路径分隔符 + 常见文件扩展名
    if re.search(r'[\\/]', value) and re.search(r'\.\w{1,10}$', value):
        return True

    # 5. 磁盘上真实存在（最强信号）
    if os.path.exists(value):
        return True

    return False


EXECUTE_PROMPT = """你正在执行一个任务计划的第 {step_id} 步（共 {total_steps} 步）。

当前步骤: {step_task}

之前步骤的结果（含 list_files 输出的真实文件列表）:
{previous_results}

请完成这个步骤。仔细查看上面"之前步骤的结果"中的文件列表，从中选出实际存在的文件路径。

规则：
- 如果需要读取文件 → 输出 action + action_input，file_path 必须从上方的文件列表中复制
- 如果文件列表中找不到对应的文件 → 输出 result 说明"该文件不存在，跳过"
- 如果不需要工具 → 直接输出 result
- 绝对禁止编造不在文件列表中的路径

输出格式（只输出一个 JSON）：
- 需要工具: {{"thought": "...", "action": "工具名", "action_input": {{"参数": "值"}}}}
- 不需要工具: {{"thought": "...", "result": "你的分析/总结内容"}}
"""


class PlanExecuteEngine:
    """规划-执行两阶段引擎。"""

    def __init__(
        self,
        model_priority: list[str],
        *,
        max_steps: int = 20,
        system_prompt: str | None = None,
        callback: EngineCallback | None = None,
    ) -> None:
        self.model_priority = model_priority
        self.max_steps = max_steps
        self.system_prompt = system_prompt or PLAN_SYSTEM_PROMPT
        self.callback = callback or EngineCallback()

    def run(self, user_input: str, context: AgentContext | None = None) -> str:
        """
        执行 Plan-Execute 流程。

        对于探索类任务，先静默侦察目录结构，再生成计划。
        """
        ctx = context or AgentContext()
        tracker = ToolExecutionTracker()

        # Phase 0: Scout — 如果任务涉及本地目录，先 list_files 获取真实文件列表
        scout_info = self._scout(user_input, ctx, tracker)
        plan_input = user_input
        if scout_info:
            plan_input = f"{user_input}\n\n## 🔴 项目的真实文件列表（来自 list_files，请基于此规划）\n```\n{scout_info}\n```\n请使用上述真实文件路径来规划 read_file 步骤。"

        # Phase 1: Planning（现在有真实文件列表）
        logger.debug("Plan-Execute Phase 1: 规划中...")
        plan = self._plan(plan_input, ctx)
        steps = plan.get("steps", [])

        if not steps:
            self.callback.on_warning("未能生成有效的执行计划")
            return plan.get("analysis", "未能生成有效的执行计划。")

        logger.debug(f"计划生成 {len(steps)} 个步骤")
        total = min(len(steps), self.max_steps)

        # Phase 2: Execution
        logger.debug("Plan-Execute Phase 2: 执行中...")
        results = []

        for i, step in enumerate(steps[:self.max_steps]):
            step_id = step.get("id", i + 1)
            step_task = step.get("task", "")
            tool = step.get("tool")
            params = step.get("params", {})

            logger.debug(f"执行步骤 {step_id}: {step_task}")
            self.callback.on_step(step_id, total, step_task)

            # 构建上下文提示
            prev_results = "\n".join(
                f"步骤 {r['step_id']}: {r['result'][:200]}"
                for r in results[-3:]  # 只保留最近 3 步
            ) if results else "(无)"

            if tool and tool != "null":
                # 使用工具执行
                result = self._execute_step_with_tool(tool, params, ctx, tracker)
            else:
                # 使用 LLM 执行 — 支持 mini ReAct 循环
                result = self._execute_step_with_llm(
                    step_id, len(steps), step_task, prev_results, user_input, tracker, ctx
                )

            results.append({
                "step_id": step_id,
                "task": step_task,
                "result": result,
            })

            ctx.set(f"step_{step_id}_result", result)
            success = not result.startswith(("执行失败", "执行异常"))
            self.callback.on_step_done(step_id, success, result[:200])
            logger.debug(f"步骤 {step_id} 完成: {result[:100]}")

        # 汇总结果 — 附加工具执行摘要
        return self._summarize(user_input, plan.get("analysis", ""), results, tracker)

    @staticmethod
    def _extract_directory(text: str) -> str | None:
        """从用户输入中提取目标目录路径。"""
        import re
        # Windows 绝对路径: D:\xxx 或 C:\xxx
        m = re.search(r'([A-Za-z]:[\\/][^\s,，。；;]+)', text)
        if m:
            path = m.group(1).rstrip('\\/')
            return path
        # Unix 绝对路径: /home/xxx
        m = re.search(r'(/[^\s,，。；;]{2,})', text)
        if m:
            return m.group(1).rstrip('/')
        # 相对路径: ./xxx 或 ../xxx
        m = re.search(r'(\.\.?/[^\s,，。；;]+)', text)
        if m:
            return m.group(1).rstrip('/')
        return None

    def _scout(
        self, user_input: str, context: AgentContext,
        tracker: ToolExecutionTracker,
    ) -> str | None:
        """Phase 0: 静默侦察 — 列出目标目录的文件结构，为规划提供真实数据。"""
        import os
        target_dir = self._extract_directory(user_input)
        if not target_dir:
            return None
        # 只对存在的本地目录进行侦察
        if not os.path.isdir(target_dir):
            return None

        logger.info(f"Plan-Execute Scout: 侦察目录 {target_dir}")
        self.callback.on_think(f"Scout: 侦察目录结构 {target_dir} ...")

        # 调用 ToolNode 执行 list_files
        try:
            from omniagent.nodes.tool_node import ToolNode

            def _fmt_files(result: dict) -> str:
                """从 ToolNode 结果中提取文件列表并格式化为文本。"""
                if not result.get("success"):
                    return ""
                # ToolNode 返回 {'files': [...], 'count': N, ...}
                files = result.get("files", [])
                if files:
                    return "\n".join(str(f) for f in files)
                # 回退：尝试 content/stdout
                for key in ("content", "stdout", "output"):
                    val = result.get(key)
                    if val and isinstance(val, str) and len(val) > 10:
                        return val
                return str(result)[:3000]

            # 根目录列表
            node = ToolNode("scout_root", action_type="list_files", file_path=target_dir)
            result = node.execute(context)
            root_files = _fmt_files(result)

            # 递归列表（Python 文件）
            node2 = ToolNode("scout_recursive", action_type="list_files", file_path=target_dir, pattern="**/*.py")
            result2 = node2.execute(context)
            py_files = _fmt_files(result2)

            scout_text = (
                f"根目录文件 ({target_dir}):\n{root_files[:3000]}\n\n"
                f"所有 Python 文件 (递归):\n{py_files[:3000]}"
            )
            if tracker:
                tracker.record("list_files", {"file_path": target_dir}, True, root_files[:200])
            logger.info(f"Plan-Execute Scout: 完成 ({len(scout_text)} chars)")
            return scout_text
        except Exception as e:
            logger.warning(f"Plan-Execute Scout 失败: {e}")
            return None

    def _plan(self, user_input: str, context: AgentContext | None = None) -> dict[str, Any]:
        """Phase 1: 生成执行计划。"""
        messages = [{"role": "system", "content": self.system_prompt}]
        # 注入对话历史（最近 10 条，包括 system 消息以保留 prompt_optimizer 的 system_hint）
        if context:
            history = context.get_conversation_messages()
            if history:
                # 取最近的非 system 消息 + 最近的 system 消息（含 system_hint）
                non_system = [m for m in history if m.get("role") != "system"][-6:]
                system_msgs = [m for m in history if m.get("role") == "system"][-2:]
                recent = system_msgs + non_system
                messages.extend(recent)
                logger.debug(f"Plan 注入 {len(recent)} 条对话历史 (含 {len(system_msgs)} 条 system)")
            else:
                logger.warning("Plan: 无对话历史可注入！")
        else:
            logger.warning("Plan: context 为 None！")

        # 关键：将当前用户输入加入消息列表
        messages.append({"role": "user", "content": user_input})

        response = self._call_llm(messages)
        if not response or not response.strip():
            logger.warning("LLM 返回了空响应！请检查 API 配置和模型是否支持。")
        else:
            logger.debug(f"LLM 原始响应 (前500字): {response[:500]}")
        result = self._parse_json(response)
        logger.debug(f"解析后: steps={len(result.get('steps', []))}, analysis={result.get('analysis', '')[:100]}")
        return result

    def _execute_step_with_tool(
        self, tool: str, params: dict, context: AgentContext,
        tracker: ToolExecutionTracker | None = None,
    ) -> str:
        """使用工具执行步骤。包含参数验证。"""
        # ── 参数验证：文件路径不能是自然语言描述 ──
        validated = _validate_tool_params(tool, params)
        if not validated["valid"]:
            error_msg = f"参数错误: {validated['reason']}"
            if tracker:
                tracker.record(tool, params, False, error_msg, error=error_msg)
            return error_msg

        try:
            params = ToolNode.normalize_params(params)
            self.callback.on_act(tool, params)
            node = ToolNode(f"plan_{tool}", action_type=tool, **params)
            result = node.execute(context)

            success = result.get("success", False)
            error = result.get("error")

            if success:
                summary = ""
                for key in ("content", "stdout", "output", "files"):
                    if result.get(key):
                        val = result[key]
                        if isinstance(val, list):
                            summary = "\n".join(str(v) for v in val[:30])
                        else:
                            summary = str(val)[:2000]
                        break
                if not summary:
                    summary = "执行成功"

                if tracker:
                    tracker.record(tool, params, True, summary[:200])
                self.callback.on_observe(summary)
                return summary
            error_detail = f"执行失败: {error or result}"
            if tracker:
                tracker.record(tool, params, False, error_detail, error=str(error))
            self.callback.on_observe(error_detail)
            return error_detail

        except Exception as e:
            error_msg = f"执行异常: {e}"
            if tracker:
                tracker.record(tool, params, False, error_msg, error=str(e))
            self.callback.on_observe(error_msg)
            return error_msg

    def _execute_step_with_llm(
        self, step_id: int, total: int, task: str, prev_results: str, original: str,
        tracker: ToolExecutionTracker | None = None,
        context: AgentContext | None = None,
    ) -> str:
        """使用 LLM 执行不需要工具的步骤。支持 mini ReAct 循环（最多 3 次工具调用）。"""
        prompt = EXECUTE_PROMPT.format(
            step_id=step_id, total_steps=total,
            step_task=task, previous_results=prev_results,
        )
        messages: list[dict[str, str]] = [
            {"role": "system", "content": f"原始任务: {original}"},
            {"role": "user", "content": prompt},
        ]

        # ── mini ReAct 循环（最多 3 次工具调用）──
        for _ in range(3):
            response = self._call_llm(messages)
            parsed = parse_react(response)  # 用 ReAct 解析器提取 action/result

            # 检查是否有 action（工具调用）
            action = parsed.get("action", "")
            if action and action.strip():
                action_input = parsed.get("action_input", {}) or {}
                # 验证参数
                validated = _validate_tool_params(action, action_input)
                if not validated["valid"]:
                    messages.append({"role": "assistant", "content": response})
                    messages.append({"role": "user", "content": f"参数错误: {validated['reason']}。请修正。"})
                    continue

                # 执行工具
                ctx = context or AgentContext()
                tool_result = self._execute_step_with_tool(action, action_input, ctx, tracker)
                messages.append({"role": "assistant", "content": response[:500]})
                messages.append({"role": "user", "content": f"工具 '{action}' 执行结果:\n{tool_result[:2000]}\n\n请继续完成当前步骤，或输出 {{\"result\": \"...\"}}。"})
                continue

            # 检查是否有 result/final_answer
            result_text = parsed.get("result", "") or parsed.get("final_answer", "")
            if result_text and result_text.strip():
                return self._verify_llm_file_claims(result_text, tracker)

            # 纯文本响应 → 直接返回
            return self._verify_llm_file_claims(response, tracker)

        # 耗尽 mini ReAct 循环 → 返回最后的响应
        last_content = messages[-1].get("content", "") if messages else ""
        return self._verify_llm_file_claims(str(last_content), tracker)

    @staticmethod
    def _verify_llm_file_claims(
        llm_output: str, tracker: ToolExecutionTracker | None = None,
    ) -> str:
        """检查 LLM 输出中是否声称创建/写入了文件，但实际未通过工具执行。

        如果检测到未验证的文件声明，追加警告信息。
        """
        import re

        # 检测文件操作声明的关键词
        claim_patterns = [
            r"(?:已|已经|成功)?(?:创建|新建|生成|写入|保存)(?:了)?",
            r"(?:created|written|saved|generated|initialized|made)",
            r"(?:文件|目录|文件夹)(?:已|已经)",
        ]

        has_claim = any(re.search(p, llm_output, re.IGNORECASE) for p in claim_patterns)
        if not has_claim:
            return llm_output

        # 提取提到的文件路径
        file_patterns = [
            r'[\w/\\.-]+\.(?:py|js|ts|html|css|json|yaml|yml|toml|md|txt|sh|bat|ps1|go|rs|java|c|cpp|h)',
            r'(?:src|lib|app|test|tests|dist|build|bin|config|docs)[/\\][\w/\\.-]+',
        ]
        mentioned_files = set()
        for pattern in file_patterns:
            mentioned_files.update(re.findall(pattern, llm_output))

        if not mentioned_files:
            return llm_output

        # 检查哪些文件真的通过工具创建了
        verified_files = set()
        if tracker:
            for call in tracker.calls:
                if call.success and call.tool_name in ("write_file", "create_directory"):
                    fp = call.params.get("file_path", "")
                    if fp:
                        verified_files.add(fp)

        # 对每个提到的文件，验证是否真的存在或被工具创建
        unverified = []
        for f in mentioned_files:
            if f in verified_files:
                continue
            from pathlib import Path
            if not Path(f).exists():
                unverified.append(f)

        if unverified:
            warning = (
                f"\n\n⚠️ **注意**: 以上内容中提到了创建文件 "
                f"`{'`, `'.join(unverified)}`，"
                f"但这些文件未经工具验证，可能并未实际创建。"
                f"如需真正创建文件，请使用 write_file 工具。"
            )
            return llm_output + warning

        return llm_output

    def _summarize(
        self, original: str, analysis: str, results: list[dict],
        tracker: ToolExecutionTracker | None = None,
    ) -> str:
        """汇总所有步骤的结果。包含空洞检测。"""
        results_text = "\n".join(
            f"步骤 {r['step_id']} ({r['task']}): {r['result'][:300]}"
            for r in results
        )

        # 构建工具执行摘要
        tool_summary = ""
        if tracker and tracker.has_executions():
            tool_summary = f"\n\n工具执行记录:\n{tracker.detail_log()}"

        messages = [
            {"role": "system", "content": (
                "请根据以下执行结果，给出简洁的最终总结。"
                "如果某些步骤声称创建了文件但没有对应的工具执行记录，"
                "请在总结中明确指出这些文件可能并未实际创建。"
            )},
            {"role": "user", "content": (
                f"原始任务: {original}\n\n分析: {analysis}\n\n"
                f"执行结果:\n{results_text}{tool_summary}"
            )},
        ]
        summary = self._call_llm(messages)

        # ── 空洞检测 ──
        hollow_check = _check_hollow_answer(summary, original, tracker)
        if hollow_check["is_hollow"]:
            logger.warning(f"PlanExecute: 汇总结果空洞 — {hollow_check['reason']}，追加警告")
            warning = (
                f"\n\n⚠️ **注意**: 以上总结可能不够完整（{hollow_check['reason']}）。"
                f"请查看各步骤的详细执行结果获取更完整的信息。"
            )
            return summary + warning

        return summary

    def _call_llm(self, messages: list[dict[str, str]], max_tokens: int = 131072) -> str:
        """调用 LLM，支持多模型 fallback。"""
        last_error = None
        for model_id in self.model_priority:
            try:
                return chat_completion(model_id, messages, max_tokens=max_tokens, temperature=0.3)
            except Exception as e:
                last_error = e
                logger.warning(f"模型 {model_id} 失败: {e}")
        msg = f"所有模型均调用失败: {last_error}"
        raise RuntimeError(msg)

    def _parse_json(self, text: str) -> dict[str, Any]:
        """从 LLM 输出中提取 JSON（委托给 response_adapter 中间件）。"""
        return parse_plan(text)
