"""
Batch tools — batch_write, batch_edit
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from omniagent.engine.context import AgentContext
from omniagent.tools.builtin.base import MAX_WRITE_SIZE, BaseTool

logger = logging.getLogger(__name__)


class BatchWriteTool(BaseTool):
    name = "batch_write"

    def execute(self, context: AgentContext) -> dict[str, Any]:
        files = self._extra.get("files", [])
        if not files:
            return {"action_type": "batch_write", "success": False, "error": "需要 files 参数 ([{path:..., content:...}])"}

        results = []
        for i, spec in enumerate(files):
            path_str = spec.get("path") or spec.get("file_path", "")
            file_content = spec.get("content", "")
            if not path_str:
                results.append({"index": i, "success": False, "error": "缺少 path"})
                continue

            path = self._validate_path(path_str, for_write=True)
            content_bytes = len(file_content.encode(self.encoding))
            if content_bytes > MAX_WRITE_SIZE:
                results.append({"index": i, "path": str(path), "success": False, "error": f"内容过大: {content_bytes} 字节"})
                continue

            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(file_content, encoding=self.encoding)

            verify_err = self._verify_write(path, file_content)
            if verify_err:
                results.append({"index": i, "path": str(path), "success": False, "error": verify_err})
            else:
                results.append({"index": i, "path": str(path), "success": True, "bytes": content_bytes})

        all_ok = all(r.get("success") for r in results)
        return {"action_type": "batch_write", "total": len(files), "success_count": sum(1 for r in results if r.get("success")), "success": all_ok, "results": results}

    def _verify_write(self, path: Path, expected: str) -> str | None:
        if not path.exists():
            return f"验证失败: {path} 不存在"
        actual = path.read_text(encoding=self.encoding)
        if actual != expected:
            return f"内容验证失败"
        return None


class BatchEditTool(BaseTool):
    name = "batch_edit"

    def execute(self, context: AgentContext) -> dict[str, Any]:
        edits = self._extra.get("edits", [])
        if not edits:
            return {"action_type": "batch_edit", "success": False, "error": "需要 edits 参数"}

        results = []
        for i, spec in enumerate(edits):
            fp = spec.get("file_path", "")
            old = spec.get("old_text", "")
            new = spec.get("new_text", "")
            if not fp or not old:
                results.append({"index": i, "success": False, "error": "缺少 file_path 或 old_text"})
                continue
            try:
                path = self._validate_path(fp, for_write=True)
                if not path.exists():
                    results.append({"index": i, "file": str(path), "success": False, "error": f"文件不存在: {path}"})
                    continue
                content = path.read_text(encoding=self.encoding)
                count = content.count(old)
                if count == 0:
                    results.append({"index": i, "file": str(path), "success": False, "error": "未找到匹配文本"})
                elif count > 1:
                    results.append({"index": i, "file": str(path), "success": False, "error": f"找到 {count} 处匹配"})
                else:
                    path.write_text(content.replace(old, new, 1), encoding=self.encoding)
                    results.append({"index": i, "file": str(path), "success": True, "replacements": 1})
            except Exception as e:
                results.append({"index": i, "success": False, "error": f"编辑异常: {e}"})

        all_ok = all(r.get("success") for r in results)
        return {"action_type": "batch_edit", "total": len(edits), "success_count": sum(1 for r in results if r.get("success")), "success": all_ok, "results": results}
