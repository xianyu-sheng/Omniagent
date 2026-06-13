"""文件操作前自动 checkpoint — 借鉴 Claude Code 的 git stash 保护。

在 write_file / edit_file / file_move 等破坏性操作前自动保存文件副本，
操作成功保留副本供恢复，操作失败自动还原。

使用方式:
    from omniagent.engine.checkpoint import CheckpointManager
    ckpt = CheckpointManager()

    # 写前保存
    ckpt.save(path)  # 如果文件存在则备份

    # 写成功 → 保留备份（可手动清理）
    ckpt.keep(path)

    # 写失败 → 还原文件
    ckpt.restore(path)
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

_CHECKPOINT_DIR_NAME = ".omniagent/checkpoints"


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:-3]


class CheckpointManager:
    """文件 checkpoint 管理器。

    在破坏性文件操作前自动备份，支持事后还原。

    Features:
    - 自动保存: write/edit/move 前备份目标文件
    - 操作失败自动还原: 文件写坏时恢复到操作前状态
    - 操作成功保留备份: 用户可通过 /checkpoint 命令恢复
    - 批量还原: 支持一次性还原本次会话所有修改
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base = (base_dir or Path.cwd()) / _CHECKPOINT_DIR_NAME
        self._base.mkdir(parents=True, exist_ok=True)
        # 记录本次会话的 checkpoint
        self._session: dict[str, Path] = {}  # file_path → backup_path

    # ── 公共 API ──────────────────────────────────────────────

    def save(self, file_path: str | Path) -> bool:
        """保存文件的 checkpoint 副本。

        如果文件不存在则跳过（不报错）。
        返回 True 表示已保存备份，False 表示文件不存在无需保存。
        """
        path = Path(file_path).resolve()
        if not path.exists():
            return False

        # 确保不在已保存列表中重复
        key = str(path)
        if key in self._session:
            return True  # 已有备份

        backup_dir = self._base / _ts()
        backup_dir.mkdir(parents=True, exist_ok=True)

        # 备份文件名包含原始路径信息
        backup_name = self._path_to_backup_name(path)
        backup_path = backup_dir / backup_name

        if path.is_file():
            shutil.copy2(path, backup_path)
        elif path.is_dir():
            shutil.copytree(path, backup_path, symlinks=True)

        self._session[key] = backup_path
        logger.debug(f"Checkpoint 已保存: {path} → {backup_path}")
        return True

    def restore(self, file_path: str | Path) -> bool:
        """从 checkpoint 还原文件。

        用于操作失败时回滚。
        返回 True 表示已还原。
        """
        path = Path(file_path).resolve()
        key = str(path)

        backup_path = self._session.pop(key, None)
        if backup_path is None or not backup_path.exists():
            logger.debug(f"Checkpoint 还原跳过（无备份）: {path}")
            return False

        try:
            # 删除当前文件/目录
            if path.exists():
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()

            # 还原备份
            if backup_path.is_dir():
                shutil.copytree(backup_path, path, symlinks=True)
            else:
                shutil.copy2(backup_path, path)

            # 清理备份
            shutil.rmtree(backup_path.parent, ignore_errors=True)

            logger.info(f"Checkpoint 已还原: {path} (从 {backup_path})")
            return True
        except Exception as e:
            logger.error(f"Checkpoint 还原失败: {path} — {e}")
            return False

    def keep(self, file_path: str | Path) -> None:
        """标记文件备份为已确认（操作成功后保留备份）。"""
        path = Path(file_path).resolve()
        key = str(path)
        if key in self._session:
            logger.debug(f"Checkpoint 已保留: {path} (备份: {self._session[key]})")

    def discard(self, file_path: str | Path) -> None:
        """丢弃 checkpoint 备份并清理文件。"""
        path = Path(file_path).resolve()
        key = str(path)
        backup_path = self._session.pop(key, None)
        if backup_path and backup_path.parent.exists():
            shutil.rmtree(backup_path.parent, ignore_errors=True)
            logger.debug(f"Checkpoint 已清理: {path}")

    def list_all(self) -> list[dict[str, Any]]:
        """列出所有 checkpoint 备份。

        Returns:
            列表，每项: {file: 原始路径, backup: 备份路径, time: 时间戳}
        """
        return [
            {
                "file": self._backup_name_to_path(backup_file.name),
                "backup": str(backup_file),
                "time": backup_dir.name,
            }
            for backup_dir in sorted(self._base.iterdir(), reverse=True)
            if backup_dir.is_dir()
            for backup_file in backup_dir.iterdir()
        ]

    def rollback_all(self, dry_run: bool = False) -> list[str]:
        """还原本次会话中所有已 checkpoint 的文件。

        Args:
            dry_run: True 时只列出将要还原的文件，不实际还原。

        Returns:
            已还原（或将还原）的文件路径列表。
        """
        files = list(self._session.keys())
        if dry_run:
            return files

        return [fp for fp in files if self.restore(fp)]

    # ── 上下文管理器 ──────────────────────────────────────────

    class Guard:
        """with 语句保护器: 进入时保存，退出时根据成功/失败决定保留/还原。"""

        def __init__(self, manager: CheckpointManager, file_path: str | Path):
            self._manager = manager
            self._path = Path(file_path)
            self._saved = False

        def __enter__(self) -> CheckpointManager.Guard:
            self._saved = self._manager.save(self._path)
            return self

        def __exit__(self, exc_type: type | None, exc_val: BaseException | None,
                     exc_tb: object) -> Literal[False]:
            if exc_type is not None:
                # 异常 → 还原
                if self._saved:
                    self._manager.restore(self._path)
            else:
                # 正常退出 → 保留备份
                if self._saved:
                    self._manager.keep(self._path)
            return False  # 不吞异常

    def guard(self, file_path: str | Path) -> Guard:
        """返回一个上下文管理器，自动处理保存/还原。

        使用方式:
            with checkpoint.guard("app.py"):
                path.write_text("new content")
            # 正常退出 → 备份保留
            # 异常退出 → 自动还原
        """
        return self.Guard(self, file_path)

    # ── 辅助方法 ──────────────────────────────────────────────

    @staticmethod
    def _path_to_backup_name(path: Path) -> str:
        """将文件路径转为备份文件名。"""
        # app.py → app.py
        # src/app.py → src_app.py
        return str(path).replace("\\", "/").replace(":", "").replace("/", "_")

    @staticmethod
    def _backup_name_to_path(name: str) -> str:
        """将备份文件名转回原始路径（近似）。"""
        # src_app.py → src/app.py
        return name.replace("_", "/", 1) if "_" in name else name


# ── 全局单例 ────────────────────────────────────────────────

_global_checkpoint: CheckpointManager | None = None


def get_checkpoint() -> CheckpointManager:
    """获取全局 CheckpointManager 单例。"""
    global _global_checkpoint
    if _global_checkpoint is None:
        _global_checkpoint = CheckpointManager()
    return _global_checkpoint
