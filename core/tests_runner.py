# core/tests_runner.py
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, Signal, QProcess


BEST_RE = re.compile(r"^\s*Best strategy:\s*(.+?)\s*$", re.IGNORECASE)


@dataclass
class TestStartParams:
    base_dir: str  # корень приложения, где utils\
    ps_exe: str = "powershell"  # Windows PowerShell 5.1
    timeout_ms: int = 0  # 0 = без таймаута (если захочешь добавить позже)


class TestsRunner(QObject):
    line = Signal(str)              # любая строка вывода
    best_strategy = Signal(str)     # только когда нашли Best strategy
    finished = Signal(int)          # exit code
    started = Signal()
    error = Signal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._p: Optional[QProcess] = None
        self._buf = ""  # буфер для разбиения на строки

    def is_running(self) -> bool:
        return self._p is not None and self._p.state() == QProcess.Running

    def stop(self) -> None:
        if self._p is None:
            return
        self._p.kill()

    def start(self, params: TestStartParams) -> None:
        if self.is_running():
            self.error.emit("Тест уже запущен")
            return

        ps1 = os.path.join(os.path.abspath(params.base_dir), "utils", "test zapret.ps1")
        if not os.path.isfile(ps1):
            self.error.emit(f"Не найден файл теста: {ps1}")
            return

        p = QProcess(self)
        self._p = p

        # Чтобы всё (stdout+stderr) шло одним потоком
        p.setProcessChannelMode(QProcess.MergedChannels)  # важно вызвать до start() [web:22]

        p.started.connect(self.started)
        p.readyReadStandardOutput.connect(self._on_ready)
        p.finished.connect(self._on_finished)

        # Важно: -File не даёт удобно собрать все PowerShell streams.
        # Поэтому запускаем через -Command и делаем *>&1 (сливаем streams в success stream). [web:26]
        cmd = (
            f"& {{ "
            f"$ProgressPreference='SilentlyContinue'; "
            f"& '{ps1}' "
            f"}} *>&1"
        )

        args = [
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-Command", cmd,
        ]

        p.start(params.ps_exe, args)

    def _emit_line(self, s: str) -> None:
        s = s.rstrip("\r\n")
        if not s:
            return
        self.line.emit(s)
        m = BEST_RE.match(s)
        if m:
            self.best_strategy.emit(m.group(1))

    def _on_ready(self) -> None:
        if self._p is None:
            return
        data = bytes(self._p.readAllStandardOutput()).decode("utf-8", errors="replace")
        if not data:
            return

        self._buf += data
        while True:
            pos = self._buf.find("\n")
            if pos < 0:
                break
            line = self._buf[:pos + 1]
            self._buf = self._buf[pos + 1:]
            self._emit_line(line)

    def _on_finished(self, code: int, _status) -> None:
        # добиваем остаток буфера
        if self._buf.strip():
            self._emit_line(self._buf)
        self._buf = ""
        self.finished.emit(int(code))
        self._p = None
