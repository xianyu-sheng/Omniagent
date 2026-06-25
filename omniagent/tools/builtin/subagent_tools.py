"""
Subagent tools — spawn_agent, agent_result (从 engine/subagent.py 注册到主路径)
"""

from __future__ import annotations

import logging
from typing import Any

from omniagent.engine.context import AgentContext
from omniagent.tools.builtin.base import BaseTool

logger = logging.getLogger(__name__)


class SpawnAgentTool(BaseTool):
    """派生子 Agent 在后台处理子任务。"""
    name = "spawn_agent"

    def execute(self, context: AgentContext) -> dict[str, Any]:
        goal = str(self._extra.get("goal", ""))
        model = str(self._extra.get("model", "") or "")
        capability = str(self._extra.get("capability", "") or "general-purpose")
        context_seed = self._extra.get("context_seed", None)

        if not goal:
            return {"action_type": "spawn_agent", "success": False, "error": "需要 goal 参数（子任务目标）"}

        try:
            from omniagent.engine.subagent import SpawnAgentTool as _Spawn, get_background_registry
            import asyncio

            spawn = _Spawn()
            params: dict[str, Any] = {
                "goal": goal,
                "capability": capability,
            }
            if model:
                params["model"] = model
            if context_seed is not None:
                params["context_seed"] = context_seed

            result = asyncio.run(spawn.invoke(params))
            return {
                "action_type": "spawn_agent", "success": not result.is_error,
                "content": result.content, "error": result.content if result.is_error else None,
                "task_id": result.metadata.get("task_id", ""),
            }
        except ImportError:
            return {"action_type": "spawn_agent", "success": False, "error": "子 Agent 系统不可用"}
        except Exception as e:
            return {"action_type": "spawn_agent", "success": False, "error": str(e)}


class AgentResultTool(BaseTool):
    """查询子 Agent 任务结果。"""
    name = "agent_result"

    def execute(self, context: AgentContext) -> dict[str, Any]:
        task_id = str(self._extra.get("task_id", ""))

        try:
            from omniagent.engine.subagent import AgentResultTool as _Result
            import asyncio

            result_tool = _Result()
            params = {"task_id": task_id} if task_id else {}
            result = asyncio.run(result_tool.invoke(params))

            return {
                "action_type": "agent_result", "success": not result.is_error,
                "content": result.content, "error": result.content if result.is_error else None,
            }
        except ImportError:
            return {"action_type": "agent_result", "success": False, "error": "子 Agent 系统不可用"}
        except Exception as e:
            return {"action_type": "agent_result", "success": False, "error": str(e)}
