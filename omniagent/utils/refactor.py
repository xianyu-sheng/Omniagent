"""
Refactor — 代码重构工具集。

组合代码索引 + AST 分析 + 批量编辑，提供：
- 跨文件符号重命名
- 未使用导入清理
- 函数提取
- 语法安全验证
"""

from __future__ import annotations

import logging
import re
import ast
from pathlib import Path
from typing import Any

from omniagent.utils.code_index import CodeIndex, Symbol
from omniagent.utils.ast_analyzer import ASTAnalyzer

logger = logging.getLogger(__name__)


class RefactorEngine:
    """重构引擎。"""

    def __init__(self, root_dir: str | Path = ".") -> None:
        self.root = Path(root_dir).resolve()
        self.index = CodeIndex(root_dir)
        self.analyzer = ASTAnalyzer()

    def build_index(self, max_files: int = 500) -> int:
        """构建代码索引。"""
        return self.index.build(max_files)

    def rename_symbol(
        self,
        old_name: str,
        new_name: str,
        *,
        file_filter: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """跨文件重命名符号。

        Args:
            old_name: 旧符号名
            new_name: 新符号名
            file_filter: 可选的文件过滤 glob
            dry_run: 只预览不实际修改

        Returns:
            {"changes": [...], "errors": [...], "success": bool}
        """
        changes = []
        errors = []

        # 查找所有引用
        refs = self.index.find_references(old_name, limit=1000)
        if not refs:
            return {"changes": [], "errors": [f"未找到 '{old_name}' 的引用"], "success": False}

        # 按文件分组
        files_to_edit: dict[str, list[tuple[int, int]]] = {}
        for ref in refs:
            if file_filter and not self._match_filter(ref.file_path, file_filter):
                continue
            files_to_edit.setdefault(ref.file_path, []).append((ref.line, ref.col))

        # 逐文件替换
        for file_path, positions in files_to_edit.items():
            try:
                content = Path(file_path).read_text(encoding="utf-8")
                lines = content.splitlines(keepends=True)

                # 从后往前替换，避免偏移
                modified = False
                for line_no, col in sorted(positions, reverse=True):
                    if line_no <= len(lines):
                        line = lines[line_no - 1]
                        # 精确替换（词边界）
                        new_line = re.sub(
                            r'\b' + re.escape(old_name) + r'\b',
                            new_name,
                            line,
                        )
                        if new_line != line:
                            lines[line_no - 1] = new_line
                            modified = True
                            changes.append({
                                "file": file_path,
                                "line": line_no,
                                "old": line.rstrip(),
                                "new": new_line.rstrip(),
                            })

                if modified and not dry_run:
                    new_content = "".join(lines)
                    # 验证语法
                    if file_path.endswith(".py"):
                        syntax_errors = self.analyzer.check_syntax(new_content)
                        if syntax_errors:
                            errors.append(f"{file_path}: 重命名后语法错误 — {syntax_errors[0]}")
                            continue
                    Path(file_path).write_text(new_content, encoding="utf-8")

            except Exception as e:
                errors.append(f"{file_path}: {e}")

        return {
            "changes": changes,
            "errors": errors,
            "success": len(errors) == 0,
            "files_modified": len(changes),
        }

    def clean_unused_imports(
        self,
        file_path: str | Path,
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """清理未使用的导入。"""
        path = Path(file_path)
        if not path.exists():
            return {"success": False, "error": f"文件不存在: {path}"}

        analysis = self.analyzer.analyze_file(path)
        if not analysis.syntax_valid:
            return {"success": False, "error": f"语法错误: {analysis.syntax_errors}"}

        if not analysis.unused_imports:
            return {"success": True, "removed": [], "message": "没有未使用的导入"}

        content = path.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)
        removed = []

        for unused_name in analysis.unused_imports:
            for i, line in enumerate(lines):
                stripped = line.strip()
                # 匹配 import X 或 from Y import X
                if re.match(rf'^import\s+{re.escape(unused_name)}(\s|$|,)', stripped):
                    removed.append({"line": i + 1, "text": stripped})
                    lines[i] = ""
                    break
                elif re.match(rf'^from\s+\S+\s+import\s+.*\b{re.escape(unused_name)}\b', stripped):
                    # from X import a, b, c — 只移除单个名字
                    new_line = re.sub(
                        rf',?\s*{re.escape(unused_name)}\s*,?\s*',
                        lambda m: ',' if m.group().startswith(',') else '',
                        line,
                    )
                    # 清理多余的逗号
                    new_line = re.sub(r'import\s*,', 'import ', new_line)
                    new_line = re.sub(r',\s*\n', '\n', new_line)
                    if new_line.strip() != stripped:
                        removed.append({"line": i + 1, "text": stripped})
                        lines[i] = new_line
                        break

        if not dry_run and removed:
            new_content = "".join(lines)
            syntax_errors = self.analyzer.check_syntax(new_content)
            if syntax_errors:
                return {
                    "success": False,
                    "error": f"清理后语法错误: {syntax_errors[0]}",
                    "removed": removed,
                }
            path.write_text(new_content, encoding="utf-8")

        return {"success": True, "removed": removed, "dry_run": dry_run}

    def analyze_for_refactor(self, file_path: str | Path) -> dict[str, Any]:
        """分析文件，给出重构建议。"""
        analysis = self.analyzer.analyze_file(file_path)
        suggestions = []

        # 高复杂度函数
        for func in analysis.functions:
            if func.complexity > 10:
                suggestions.append({
                    "type": "high_complexity",
                    "target": func.name,
                    "line": func.line,
                    "message": f"函数 '{func.name}' 复杂度 {func.complexity}，建议拆分",
                })

        # 长函数
        for func in analysis.functions:
            if func.end_line and func.end_line - func.line > 50:
                suggestions.append({
                    "type": "long_function",
                    "target": func.name,
                    "line": func.line,
                    "message": f"函数 '{func.name}' 长度 {func.end_line - func.line} 行，建议拆分",
                })

        # 未使用导入
        if analysis.unused_imports:
            suggestions.append({
                "type": "unused_imports",
                "target": ", ".join(analysis.unused_imports),
                "message": f"未使用的导入: {', '.join(analysis.unused_imports)}",
            })

        # 大类
        for cls in analysis.classes:
            if len(cls.methods) > 15:
                suggestions.append({
                    "type": "large_class",
                    "target": cls.name,
                    "line": cls.line,
                    "message": f"类 '{cls.name}' 有 {len(cls.methods)} 个方法，考虑拆分职责",
                })

        return {
            "file": str(file_path),
            "summary": analysis.summary(),
            "suggestions": suggestions,
        }

    def _match_filter(self, file_path: str, filter_pattern: str) -> bool:
        """检查文件是否匹配过滤模式。"""
        import fnmatch
        return fnmatch.fnmatch(file_path, filter_pattern) or fnmatch.fnmatch(
            Path(file_path).name, filter_pattern
        )
