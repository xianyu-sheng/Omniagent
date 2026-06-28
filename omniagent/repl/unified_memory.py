"""
Unified Memory — 统一记忆接口。

合并 MemoryStore（memory.json）和 PromptStore 的记忆层（memories/*.md），
提供单一的记忆检索和注入入口，消除双重注入问题。

PromptStore 的领域知识层（domains/*.md）保持独立，
由 PromptStore 直接管理，不合并到此接口。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class UnifiedMemory:
    """统一记忆接口 — 单一入口点搜索和注入跨会话记忆。

    内存记忆（MemoryStore）和文件记忆（PromptStore memories）
    通过此接口统一检索，REPL 只需调用一次。

    领域知识（PromptStore domains）保持独立注入路径。
    """

    def __init__(
        self,
        memory_store: Any = None,   # MemoryStore 实例（懒加载避免循环导入）
        prompt_store: Any = None,   # PromptStore 实例
    ) -> None:
        self._memory_store = memory_store
        self._prompt_store = prompt_store

    def _ensure_memory_store(self):
        """懒加载 MemoryStore。"""
        if self._memory_store is None:
            try:
                from omniagent.repl.memory import MemoryStore
                self._memory_store = MemoryStore()
            except Exception as e:
                logger.debug(f"MemoryStore 初始化失败: {e}")

    def search(
        self, user_input: str, limit: int = 5,
    ) -> list[dict[str, str]]:
        """搜索相关记忆（跨所有记忆源）。

        Returns:
            [{"source": "memory"|"prompt_memory", "content": str, "type": str}, ...]
        """
        results: list[dict[str, str]] = []

        # 源 1: MemoryStore (memory.json)
        self._ensure_memory_store()
        if self._memory_store:
            try:
                memories = self._memory_store.get_relevant(user_input, limit=limit)
                for m in memories:
                    results.append({
                        "source": "memory",
                        "content": f"[{m.type}] {m.content}",
                        "type": m.type,
                    })
            except Exception as e:
                logger.debug(f"MemoryStore 搜索失败: {e}")

        # 源 2: PromptStore 记忆层 (memories/*.md)
        if self._prompt_store:
            try:
                relevant = self._prompt_store.load_relevant_prompts(user_input)
                memories_entries = [e for e in relevant if e.source in ("agent", "user")]
                for entry in memories_entries[:limit]:
                    results.append({
                        "source": "prompt_memory",
                        "content": entry.content,
                        "type": entry.source,
                    })
            except Exception as e:
                logger.debug(f"PromptStore memories 搜索失败: {e}")

        return results[:limit]

    def format_for_prompt(self, user_input: str, limit: int = 5) -> str:
        """格式化为注入系统提示词的文本（合并所有记忆源，去重）。

        替代原先分别调用 MemoryStore.format_for_context()
        和 PromptStore.format_for_context() 的两条路径。
        """
        memories = self.search(user_input, limit=limit)
        if not memories:
            return ""

        lines = ["## 相关记忆"]
        seen = set()
        for m in memories:
            # 去重：相同内容只保留一条
            key = m["content"][:80]
            if key in seen:
                continue
            seen.add(key)

            source_tag = {"memory": "📌", "prompt_memory": "🧠"}.get(m["source"], "📝")
            lines.append(f"- {source_tag} {m['content']}")

        return "\n".join(lines)
