"""Runs cloud sync work off the UI thread so the window never freezes."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from core.exceptions import VeyraError
from core.logger import get_logger, log_unexpected
from services import sync_service

logger = get_logger("ui.sync")


class SyncWorker(QThread):
    """Executes one sync action and reports the result back on the GUI thread."""

    finished_result = Signal(object)

    def __init__(self, action, mode: str, parent=None):
        super().__init__(parent)
        self._action = action
        self._mode = mode

    def run(self) -> None:  # noqa: D102 - QThread entry point
        try:
            result = self._action()
        except VeyraError as error:
            result = sync_service.SyncResult(
                ok=False, mode=self._mode, message=error.message
            )
        except Exception as exc:  # noqa: BLE001 - never surface a traceback
            reference = log_unexpected(logger, f"cloud sync ({self._mode})", exc)
            result = sync_service.SyncResult(
                ok=False,
                mode=self._mode,
                message=f"Cloud sync hit an unexpected problem. Reference {reference}.",
            )
        self.finished_result.emit(sync_service.record(result))
