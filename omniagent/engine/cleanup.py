"""会话清理 — 自动清理过期会话、运行记录、checkpoint 备份。

可配置:
- 会话保留天数 (默认 7 天)
- 运行记录保留天数 (默认 30 天)
- checkpoint 保留天数 (默认 14 天)

使用方式:
    from omniagent.engine.cleanup import SessionCleaner
    cleaner = SessionCleaner()
    cleaner.cleanup()  # 清理所有过期数据
    stats = cleaner.stats()  # 查看存储统计
"""

from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CleanupStats:
    """清理统计。"""
    sessions_deleted: int = 0
    sessions_kept: int = 0
    runs_deleted: int = 0
    checkpoints_deleted: int = 0
    bytes_freed: int = 0


class SessionCleaner:
    """会话数据清理器。

    Features:
    - 自动清理超过保留期的会话目录
    - 清理旧运行记录
    - 清理旧 checkpoint 备份
    - 统计存储使用情况
    """

    def __init__(
        self,
        base_dir: Path | None = None,
        session_retention_days: int = 7,
        run_retention_days: int = 30,
        checkpoint_retention_days: int = 14,
    ) -> None:
        self._base = (base_dir or Path.cwd()) / ".omniagent"
        self._session_dir = self._base / "sessions"
        self._runs_dir = self._base / "runs"
        self._checkpoint_dir = self._base / "checkpoints"

        self.session_retention = session_retention_days * 86400  # 转为秒
        self.run_retention = run_retention_days * 86400
        self.checkpoint_retention = checkpoint_retention_days * 86400

    # ── 公共 API ──────────────────────────────────────────────

    def cleanup(self, dry_run: bool = False) -> CleanupStats:
        """清理过期数据。

        Args:
            dry_run: True 时只统计不删除。

        Returns:
            CleanupStats 清理统计。
        """
        stats = CleanupStats()
        now = time.time()

        # 清理过期会话
        if self._session_dir.exists():
            for session_dir in self._session_dir.iterdir():
                if not session_dir.is_dir():
                    continue
                age = now - session_dir.stat().st_mtime
                if age > self.session_retention:
                    size = self._dir_size(session_dir)
                    if not dry_run:
                        shutil.rmtree(session_dir, ignore_errors=True)
                    stats.sessions_deleted += 1
                    stats.bytes_freed += size
                else:
                    stats.sessions_kept += 1

        # 清理过期运行记录
        if self._runs_dir.exists():
            for run_dir in self._runs_dir.iterdir():
                if not run_dir.is_dir():
                    continue
                age = now - run_dir.stat().st_mtime
                if age > self.run_retention:
                    size = self._dir_size(run_dir)
                    if not dry_run:
                        shutil.rmtree(run_dir, ignore_errors=True)
                    stats.runs_deleted += 1
                    stats.bytes_freed += size

        # 清理过期 checkpoint
        if self._checkpoint_dir.exists():
            for ckpt_dir in self._checkpoint_dir.iterdir():
                if not ckpt_dir.is_dir():
                    continue
                age = now - ckpt_dir.stat().st_mtime
                if age > self.checkpoint_retention:
                    size = self._dir_size(ckpt_dir)
                    if not dry_run:
                        shutil.rmtree(ckpt_dir, ignore_errors=True)
                    stats.checkpoints_deleted += 1
                    stats.bytes_freed += size

        if not dry_run and (stats.sessions_deleted or stats.runs_deleted or stats.checkpoints_deleted):
            logger.info(
                f"清理完成: {stats.sessions_deleted} 会话, "
                f"{stats.runs_deleted} 运行记录, "
                f"{stats.checkpoints_deleted} checkpoint, "
                f"释放 {self._format_bytes(stats.bytes_freed)}"
            )

        return stats

    def stats(self) -> dict[str, Any]:
        """获取存储统计信息。"""
        return {
            "sessions": {
                "count": self._count_dirs(self._session_dir),
                "size": self._format_bytes(self._dir_size(self._session_dir)),
            },
            "runs": {
                "count": self._count_dirs(self._runs_dir),
                "size": self._format_bytes(self._dir_size(self._runs_dir)),
            },
            "checkpoints": {
                "count": self._count_dirs(self._checkpoint_dir),
                "size": self._format_bytes(self._dir_size(self._checkpoint_dir)),
            },
            "total_size": self._format_bytes(
                self._dir_size(self._session_dir)
                + self._dir_size(self._runs_dir)
                + self._dir_size(self._checkpoint_dir)
            ),
            "retention": {
                "sessions_days": self.session_retention // 86400,
                "runs_days": self.run_retention // 86400,
                "checkpoints_days": self.checkpoint_retention // 86400,
            },
        }

    # ── 辅助方法 ──────────────────────────────────────────────

    @staticmethod
    def _dir_size(path: Path) -> int:
        """计算目录总大小（字节）。"""
        if not path.exists():
            return 0
        total = 0
        try:
            for f in path.rglob("*"):
                if f.is_file():
                    total += f.stat().st_size
        except (OSError, PermissionError):
            pass
        return total

    @staticmethod
    def _count_dirs(path: Path) -> int:
        """计算子目录数量。"""
        if not path.exists():
            return 0
        return sum(1 for _ in path.iterdir() if _.is_dir())

    @staticmethod
    def _format_bytes(size: int) -> str:
        """格式化字节数。"""
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
