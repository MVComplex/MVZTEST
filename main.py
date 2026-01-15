import os
import sys
import ctypes
import tempfile
import datetime
import traceback

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QFont
from PySide6.QtNetwork import QLocalServer, QLocalSocket

# Глушим шумный лог Qt по шрифтам
os.environ.setdefault("QT_LOGGING_RULES", "qt.text.font.db=false")

BOOT_LOG = os.path.join(tempfile.gettempdir(), "MVZ_boot.log")
_SINGLE_SERVER: QLocalServer | None = None
_USER = os.getlogin() if hasattr(os, "getlogin") else "user"
_SERVER_NAME = f"MVZ_{_USER}"


def log_boot(msg: str):
    try:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(BOOT_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def relaunch_elevated() -> bool:
    """
    Перезапуск процесса с правами админа через ShellExecuteW 'runas'. [web:112][web:116]
    """
    try:
        exe = sys.executable
        params = " ".join([f'"{a}"' for a in sys.argv])
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", exe, params, None, 1
        )
        return int(rc) > 32
    except Exception:
        return False


def install_exception_hook():
    """
    Пишем крэши в BOOT_LOG и показываем диалог.
    """
    def handle_ex(exctype, value, tb):
        text = "".join(traceback.format_exception(exctype, value, tb))
        log_boot("UNHANDLED EXCEPTION:\n" + text)
        try:
            QMessageBox.critical(
                None,
                "MVZ — ошибка",
                "Произошла неперехваченная ошибка.\n"
                "Подробности записаны в лог запуска:\n" + BOOT_LOG,
            )
        except Exception:
            pass
        sys.__excepthook__(exctype, value, tb)

    sys.excepthook = handle_ex


def resource_path(relative: str) -> str:
    """
    Корректный путь к ресурсам как в dev, так и в собранном .exe.
    """
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative)


def _activate_running_instance() -> bool:
    """
    Пытаемся подключиться к уже запущенному экземпляру.
    Если удаётся — шлём ping и выходим.
    """
    sock = QLocalSocket()
    sock.connectToServer(_SERVER_NAME)
    connected = sock.waitForConnected(300)
    if not connected:
        sock.abort()
        return False
    try:
        sock.write(b"activate")
        sock.flush()
        sock.waitForBytesWritten(200)
    except Exception:
        pass
    sock.disconnectFromServer()
    return True


def _install_activation_server(window):
    """
    Локальный сервер: новые экземпляры активируют уже открытое окно. [web:101][web:106]
    """
    global _SINGLE_SERVER
    server = QLocalServer()
    try:
        QLocalServer.removeServer(_SERVER_NAME)
    except Exception:
        pass

    if not server.listen(_SERVER_NAME):
        try:
            QLocalServer.removeServer(_SERVER_NAME)
            server.listen(_SERVER_NAME)
        except Exception:
            pass

    _SINGLE_SERVER = server

    def on_new_connection():
        sock = server.nextPendingConnection()
        if not sock:
            return
        try:
            sock.waitForReadyRead(200)
            _ = bytes(sock.readAll())
        except Exception:
            pass
        sock.disconnectFromServer()
        try:
            window.showNormal()
            window.activateWindow()
            window.raise_()
        except Exception:
            window.show()

    server.newConnection.connect(on_new_connection)


def main():
    log_boot("=== MVZ start ===")
    install_exception_hook()

    # ---- Авто-поднятие прав без Qt-диалога ----
    if not is_admin():
        log_boot("Not admin, trying to relaunch elevated via ShellExecuteW(runas)")
        if relaunch_elevated():
            # Успешно запустили новый процесс с UAC — текущий выходим
            sys.exit(0)
        else:
            log_boot("Elevation failed, continue without admin")

    # Single instance
    if _activate_running_instance():
        log_boot("Other instance detected, activating and exiting.")
        return

    app = QApplication(sys.argv)
    app.setApplicationName("MVZapret (MVZ)")
    app.setOrganizationName("MVZ")
    app.setDesktopFileName("MVZapret")

    font = QFont("Segoe UI", 9)
    app.setFont(font)

    icon_path = resource_path(os.path.join("ui", "mvz-round.ico"))
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    from ui.main_window import MainWindow

    window = MainWindow()
    window.show()

    _install_activation_server(window)

    log_boot("MVZ GUI shown.")
    exit_code = app.exec()
    log_boot(f"MVZ exit: {exit_code}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
