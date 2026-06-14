"""
Code tools — code_index, ast_analyze, refactor, diff_preview
"""

from __future__ import annotations

import difflib
import logging
from pathlib import Path
from typing import Any

from omniagent.engine.context import AgentContext
from omniagent.tools.builtin.base import BaseTool

logger = logging.getLogger(__name__)


class CodeIndexTool(BaseTool):
    name = "code_index"

    def execute(self, context: AgentContext) -> dict[str, Any]:
        from omniagent.utils.code_index import CodeIndex

        query = self.resolve(self._extra.get("search_pattern", "") or self._extra.get("symbol", ""), context)
        file_path = self.resolve(self._extra.get("file_path", ""), context)

        if not query:
            return {"action_type": "code_index", "success": False, "error": "需要 search_pattern 参数"}

        root = file_path if file_path and Path(file_path).is_dir() else "."
        try:
            root = str(self._validate_path(root, for_write=False))
        except Exception:
            root = "."

        index = CodeIndex(root)
        index.build(max_files=200)
        results = index.search(query, limit=30)
        stats = index.stats()

        matches = [{"name": s.name, "kind": s.kind, "file": s.file_path, "line": s.line} for s in results]

        display = f"索引 {stats['files']} 文件, {stats['symbols']} 符号\n搜索 '{query}': {len(matches)} 匹配"
        self._write_output(context, display)
        return {"action_type": "code_index", "query": query, "total_files": stats["files"], "total_symbols": stats["symbols"], "matches": matches, "success": True}


class AstAnalyzeTool(BaseTool):
    name = "ast_analyze"

    def execute(self, context: AgentContext) -> dict[str, Any]:
        from omniagent.utils.ast_analyzer import ASTAnalyzer

        file_path = self.resolve(self._extra.get("file_path", ""), context)
        if not file_path:
            return {"action_type": "ast_analyze", "success": False, "error": "需要 file_path 参数"}

        path = self._validate_path(file_path, for_write=False)
        if not path.exists():
            return {"action_type": "ast_analyze", "success": False, "error": f"文件不存在: {path}"}

        analyzer = ASTAnalyzer()
        try:
            result = analyzer.analyze_file(path)
        except Exception as e:
            return {"action_type": "ast_analyze", "success": False, "error": f"分析失败: {e}"}

        display = result.summary()
        self._write_output(context, display)
        return {"action_type": "ast_analyze", "file": str(path), "syntax_valid": result.syntax_valid, "functions": len(result.functions), "classes": len(result.classes), "complexity": result.complexity, "unused_imports": result.unused_imports, "success": True}


class RefactorTool(BaseTool):
    name = "refactor"

    def execute(self, context: AgentContext) -> dict[str, Any]:
        from omniagent.utils.refactor import RefactorEngine

        action = self.resolve(self._extra.get("refactor_action", ""), context)
        file_path = self.resolve(self._extra.get("file_path", ""), context)

        if not action:
            return {"action_type": "refactor", "success": False, "error": "需要 refactor_action (rename|clean_imports|analyze)"}

        root = str(Path(file_path).parent) if file_path else "."
        try:
            root = str(self._validate_path(root, for_write=False))
        except Exception:
            root = "."

        engine = RefactorEngine(root)
        engine.build_index(max_files=200)

        if action == "rename":
            old_name = self.resolve(self._extra.get("old_name", ""), context)
            new_name = self.resolve(self._extra.get("new_name", ""), context)
            if not old_name or not new_name:
                return {"action_type": "refactor", "success": False, "error": "rename 需要 old_name 和 new_name"}
            result = engine.rename_symbol(old_name, new_name)
            self._write_output(context, f"重命名 '{old_name}' -> '{new_name}': {len(result['changes'])} 处")
            return {"action_type": "refactor", "refactor_action": "rename", **result}

        if action == "clean_imports":
            if not file_path:
                return {"action_type": "refactor", "success": False, "error": "clean_imports 需要 file_path"}
            result = engine.clean_unused_imports(file_path)
            self._write_output(context, f"清理导入: {file_path}")
            return {"action_type": "refactor", "refactor_action": "clean_imports", **result}

        if action == "analyze":
            if not file_path:
                return {"action_type": "refactor", "success": False, "error": "analyze 需要 file_path"}
            result = engine.analyze_for_refactor(file_path)
            self._write_output(context, result["summary"])
            return {"action_type": "refactor", "refactor_action": "analyze", **result}

        return {"action_type": "refactor", "success": False, "error": f"未知 refactor_action: {action}"}


class DiffPreviewTool(BaseTool):
    name = "diff_preview"

    def execute(self, context: AgentContext) -> dict[str, Any]:
        file_path = self.resolve(self._extra.get("file_path", ""), context)
        old_text = self.resolve(self._extra.get("old_text", ""), context)
        new_text = self.resolve(self._extra.get("new_text", ""), context)

        if not file_path:
            return {"action_type": "diff_preview", "success": False, "error": "需要 file_path"}

        path = self._validate_path(file_path, for_write=False)

        if old_text and new_text:
            if not path.exists():
                return {"action_type": "diff_preview", "success": False, "error": f"文件不存在: {path}"}
            content = path.read_text(encoding=self.encoding)
            if old_text not in content:
                return {"action_type": "diff_preview", "success": False, "error": "未找到匹配文本"}
            new_content = content.replace(old_text, new_text, 1)
        elif new_text or self._extra.get("content"):
            new_content = new_text or self._extra.get("content", "")
            content = path.read_text(encoding=self.encoding) if path.exists() else ""
        else:
            return {"action_type": "diff_preview", "success": False, "error": "需要 old_text/new_text 或 content"}

        diff = list(difflib.unified_diff(
            content.splitlines(keepends=True), new_content.splitlines(keepends=True),
            fromfile=f"a/{Path(file_path).name}", tofile=f"b/{Path(file_path).name}", lineterm="",
        ))
        diff_text = "\n".join(diff) if diff else "(无变化)"
        self._write_output(context, diff_text)
        return {"action_type": "diff_preview", "file": str(path), "diff": diff_text, "has_changes": len(diff) > 0, "success": True}
