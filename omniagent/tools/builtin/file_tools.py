"""
File tools — read_file, write_file, edit_file, list_files, search_files,
             create_directory, file_move, file_copy
"""

from __future__ import annotations

import fnmatch
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from omniagent.engine.context import AgentContext
from omniagent.tools.builtin.base import (
    MAX_READ_SIZE, MAX_WRITE_SIZE, MAX_VERIFY_SIZE, BaseTool,
)

logger = logging.getLogger(__name__)


class ReadFileTool(BaseTool):
    name = "read_file"

    def execute(self, context: AgentContext) -> dict[str, Any]:
        file_path = self.resolve(self._extra.get("file_path", ""), context)
        if not file_path:
            return {"action_type": "read_file", "success": False, "error": "需要 file_path 参数"}

        path = self._validate_path(file_path, for_write=False)
        if not path.exists():
            return {
                "action_type": "read_file", "file_path": str(path),
                "content": "", "exists": False, "success": False,
                "error": f"文件不存在: {path}",
            }

        try:
            file_size = path.stat().st_size
            if file_size > MAX_READ_SIZE:
                return {
                    "action_type": "read_file", "file_path": str(path),
                    "content": "", "exists": True, "success": False,
                    "error": f"文件过大: {file_size} 字节 (上限 {MAX_READ_SIZE})",
                }
        except OSError:
            pass

        start_line = self._extra.get("start_line")
        max_lines = self._extra.get("max_lines")

        if start_line is not None or max_lines is not None:
            all_lines = path.read_text(encoding=self.encoding).splitlines(keepends=True)
            total_lines = len(all_lines)
            s = max(1, int(start_line)) - 1 if start_line else 0
            e = s + int(max_lines) if max_lines else total_lines
            e = min(e, total_lines)
            content = "".join(all_lines[s:e])
            result = {
                "action_type": "read_file", "file_path": str(path),
                "content": content, "total_lines": total_lines,
                "from_line": s + 1, "to_line": e,
                "size": len(content), "exists": True, "success": True,
            }
        else:
            content = path.read_text(encoding=self.encoding)
            result = {
                "action_type": "read_file", "file_path": str(path),
                "content": content, "size": len(content),
                "exists": True, "success": True,
            }

        self._write_output(context, result.get("content", ""))
        return result


class WriteFileTool(BaseTool):
    name = "write_file"

    def execute(self, context: AgentContext) -> dict[str, Any]:
        file_path = self.resolve(self._extra.get("file_path", ""), context)
        content = self.resolve(self._extra.get("content", ""), context)
        append = self._extra.get("append", False)

        if not file_path:
            return {"action_type": "write_file", "success": False, "error": "需要 file_path 参数"}
        if not content and self.output_slot:
            content = context.get(self.output_slot, "")

        path = self._validate_path(file_path, for_write=True)
        content_bytes = len(content.encode(self.encoding))
        if content_bytes > MAX_WRITE_SIZE:
            return {
                "action_type": "write_file", "file_path": str(path),
                "bytes_written": 0, "success": False,
                "error": f"内容过大: {content_bytes} 字节 (上限 {MAX_WRITE_SIZE})",
            }

        path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with open(path, mode, encoding=self.encoding) as f:
            f.write(content)

        verify_err = self._verify_write(path, content, append)
        if verify_err:
            return {
                "action_type": "write_file", "file_path": str(path),
                "bytes_written": 0, "success": False, "error": verify_err,
            }

        result = {
            "action_type": "write_file", "file_path": str(path),
            "bytes_written": len(content.encode(self.encoding)),
            "append": append, "success": True,
        }
        self._write_output(context, str(path))
        return result

    def _verify_write(self, path: Path, expected: str, is_append: bool) -> str | None:
        if not path.exists():
            return f"验证失败: {path} 不存在"
        if not path.is_file():
            return f"验证失败: {path} 不是文件"
        try:
            file_size = path.stat().st_size
        except OSError:
            return "验证失败: 无法获取文件大小"
        if file_size > MAX_VERIFY_SIZE:
            return None

        try:
            actual = path.read_text(encoding=self.encoding)
        except (UnicodeDecodeError, Exception) as e:
            return None if isinstance(e, UnicodeDecodeError) else f"验证失败: {e}"

        if is_append:
            if not actual.endswith(expected) and expected not in actual:
                return "追加验证失败: 内容未在文件中找到"
        elif actual != expected:
            return f"内容验证失败: 期望 {len(expected)} 字符, 实际 {len(actual)} 字符"
        return None


class EditFileTool(BaseTool):
    name = "edit_file"

    def execute(self, context: AgentContext) -> dict[str, Any]:
        file_path = self.resolve(self._extra.get("file_path", ""), context)
        old_text = self.resolve(self._extra.get("old_text", ""), context)
        new_text = self.resolve(self._extra.get("new_text", ""), context)

        if not file_path or not old_text:
            return {"error": "需要 file_path 和 old_text 参数", "success": False}

        path = self._validate_path(file_path, for_write=True)
        if not path.exists():
            return {"error": f"文件不存在: {path}", "success": False}

        content = path.read_text(encoding=self.encoding)
        count = content.count(old_text)
        if count == 0:
            return {"error": "未找到匹配文本", "success": False}
        if count > 1:
            return {"error": f"找到 {count} 处匹配，请提供更多上下文", "success": False}

        new_content = content.replace(old_text, new_text, 1)
        path.write_text(new_content, encoding=self.encoding)

        actual = path.read_text(encoding=self.encoding)
        if actual != new_content:
            return {"file": str(path), "replacements": 0, "success": False, "error": "编辑验证失败"}

        result = {"file": str(path), "replacements": 1, "success": True}
        self._write_output(context, str(path))
        return result


class ListFilesTool(BaseTool):
    name = "list_files"

    def execute(self, context: AgentContext) -> dict[str, Any]:
        base_path = self.resolve(self._extra.get("file_path", "."), context)
        pattern = self.resolve(self._extra.get("pattern", "*"), context)
        max_depth = int(self._extra.get("max_depth", 5))

        path = self._validate_path(base_path, for_write=False)
        if not path.exists():
            return {
                "action_type": "list_files", "path": str(path),
                "files": [], "count": 0, "success": False,
                "error": f"路径不存在: {path}",
            }

        files = []
        if path.is_file():
            files.append(str(path))
        else:
            for item in self._walk(path, pattern, max_depth):
                files.append(str(item))

        display = "\n".join(files) if files else "(空目录)"
        result = {
            "action_type": "list_files", "path": str(path),
            "pattern": pattern, "files": files, "count": len(files), "success": True,
        }
        self._write_output(context, display)
        return result

    @staticmethod
    def _walk(base: Path, pattern: str, max_depth: int):
        recursive = "**" in pattern
        file_pattern = pattern.split("**/")[-1] if recursive else pattern
        base_depth = len(base.parts)
        for root, dirs, files_list in os.walk(base):
            current_depth = len(Path(root).parts) - base_depth
            if not recursive and current_depth > max_depth:
                dirs.clear()
                continue
            if current_depth > max_depth * 2:
                dirs.clear()
                continue
            for f in files_list:
                if fnmatch.fnmatch(f, file_pattern):
                    yield Path(root) / f


class SearchFilesTool(BaseTool):
    name = "search_files"

    def execute(self, context: AgentContext) -> dict[str, Any]:
        search_dir = self.resolve(self._extra.get("file_path", "."), context)
        search_pattern = self.resolve(self._extra.get("search_pattern", ""), context)
        file_filter = self.resolve(self._extra.get("file_filter", ""), context)

        if not search_pattern:
            return {"action_type": "search_files", "success": False, "error": "需要 search_pattern 参数"}

        path = self._validate_path(search_dir, for_write=False)
        if not path.exists():
            return {
                "action_type": "search_files", "path": str(path),
                "matches": [], "match_count": 0, "success": False,
                "error": f"路径不存在: {path}",
            }

        try:
            regex = re.compile(search_pattern, re.IGNORECASE)
        except re.error:
            regex = re.compile(re.escape(search_pattern), re.IGNORECASE)

        matches = []
        files_scanned = 0
        search_files_list = [path] if path.is_file() else ListFilesTool._walk(path, file_filter or "*", int(self._extra.get("max_depth", 5)))

        for fp in search_files_list:
            try:
                text = Path(fp).read_text(encoding=self.encoding, errors="ignore")
                files_scanned += 1
                for i, line in enumerate(text.splitlines(), 1):
                    if regex.search(line):
                        matches.append({"file": str(fp), "line": i, "content": line.strip()[:200]})
                        if len(matches) >= 200:
                            break
            except (OSError, UnicodeDecodeError):
                continue
            if len(matches) >= 200:
                break

        lines = [f"{m['file']}:{m['line']}: {m['content']}" for m in matches[:50]]
        display = "\n".join(lines) if lines else "(无匹配结果)"

        result = {
            "action_type": "search_files", "path": str(path), "pattern": search_pattern,
            "matches": matches, "match_count": len(matches),
            "files_scanned": files_scanned, "success": True,
        }
        self._write_output(context, display)
        return result


class CreateDirectoryTool(BaseTool):
    name = "create_directory"

    def execute(self, context: AgentContext) -> dict[str, Any]:
        dir_path = self.resolve(self._extra.get("file_path", "") or self._extra.get("action", ""), context)
        if not dir_path:
            return {"action_type": "create_directory", "success": False, "error": "需要 file_path 参数"}

        path = self._validate_path(dir_path, for_write=True)
        path.mkdir(parents=True, exist_ok=True)

        if not path.exists() or not path.is_dir():
            return {"action_type": "create_directory", "path": str(path), "success": False, "error": "创建后验证失败"}

        result = {"action_type": "create_directory", "path": str(path), "success": True}
        self._write_output(context, str(path))
        return result


class MoveFileTool(BaseTool):
    name = "file_move"

    def execute(self, context: AgentContext) -> dict[str, Any]:
        import shutil
        source = self.resolve(self._extra.get("source", ""), context)
        dest = self.resolve(self._extra.get("destination", ""), context)

        if not source or not dest:
            return {"action_type": "file_move", "success": False, "error": "需要 source 和 destination 参数"}

        src_path = self._validate_path(source, for_write=True)
        dst_path = Path(dest)

        if not src_path.exists():
            return {"action_type": "file_move", "source": str(src_path), "destination": str(dst_path), "success": False, "error": f"源文件不存在: {src_path}"}

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_path), str(dst_path))

        if not dst_path.exists():
            return {"action_type": "file_move", "source": str(src_path), "destination": str(dst_path), "success": False, "error": f"移动后验证失败: {dst_path} 不存在"}

        result = {"action_type": "file_move", "source": str(src_path), "destination": str(dst_path), "success": True}
        self._write_output(context, f"已移动: {src_path} -> {dst_path}")
        return result


class CopyFileTool(BaseTool):
    name = "file_copy"

    def execute(self, context: AgentContext) -> dict[str, Any]:
        import shutil
        source = self.resolve(self._extra.get("source", ""), context)
        dest = self.resolve(self._extra.get("destination", ""), context)

        if not source or not dest:
            return {"action_type": "file_copy", "success": False, "error": "需要 source 和 destination 参数"}

        src_path = self._validate_path(source, for_write=False)
        dst_path = Path(dest)

        if not src_path.exists():
            return {"action_type": "file_copy", "source": str(src_path), "destination": str(dst_path), "success": False, "error": f"源文件不存在: {src_path}"}

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        if src_path.is_file():
            shutil.copy2(str(src_path), str(dst_path))
        else:
            if dst_path.exists():
                dst_path = dst_path / src_path.name
            shutil.copytree(str(src_path), str(dst_path))

        result = {"action_type": "file_copy", "source": str(src_path), "destination": str(dst_path), "success": True}
        self._write_output(context, f"已复制: {src_path} -> {dst_path}")
        return result
