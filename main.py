# === MONKEY-PATCH SSL: ОТКЛЮЧАЕМ ПРОВЕРКУ СЕРТИФИКАТОВ ГЛОБАЛЬНО ===
import ssl

ssl._create_default_https_context = ssl._create_unverified_context

import os
import sys
import ctypes
import tempfile
import datetime
import traceback

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QFont
from PySide6.QtNetwork import QLocalSocket, QLocalServer

from ui.main_window import MainWindow

APP_NAME = "MVZ"
LOG_PATH = os.path.join(tempfile.gettempdir(), "mvz_boot.log")


def log_boot(msg: str) -> None:
    try:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_PATH, "a", encoding="utf-8", errors="ignore") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def request_admin_and_restart() -> None:
    try:
        script = sys.argv[0]
        params = " ".join(f'"{arg}"' for arg in sys.argv[1:])

        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, f'"{script}" {params}', None, 1
        )

        if ret > 32:
            sys.exit(0)
        else:
            QMessageBox.critical(
                None,
                "Ошибка",
                "Не удалось получить права администратора.\n"
                "MVZ требует запуск от имени администратора для работы обхода."
            )
            sys.exit(1)
    except Exception as e:
        log_boot(f"request_admin failed: {e}")
        sys.exit(1)


def _install_activation_server(window: MainWindow) -> None:
    """Single instance via QLocalServer."""
    server_name = f"{APP_NAME}_SingleInstance"

    socket = QLocalSocket()
    socket.connectToServer(server_name)

    if socket.waitForConnected(500):
        log_boot("Another instance detected, activating...")
        socket.write(b"ACTIVATE")
        socket.flush()
        socket.disconnectFromServer()
        sys.exit(0)

    server = QLocalServer()
    QLocalServer.removeServer(server_name)

    if not server.listen(server_name):
        log_boot(f"Failed to start single-instance server: {server.errorString()}")
        return

    def on_new_connection():
        client = server.nextPendingConnection()
        if client:
            client.waitForReadyRead(1000)
            data = client.readAll().data()
            if data == b"ACTIVATE":
                window.showNormal()
                window.activateWindow()
                window.raise_()
            client.disconnectFromServer()

    server.newConnection.connect(on_new_connection)
    window._single_instance_server = server


def main():
    log_boot("=== MVZ start ===")

    # Запрос прав администратора
    if not is_admin():
        log_boot("Not admin, requesting elevation...")
        request_admin_and_restart()

    log_boot("Running as admin")

    # Настройка приложения
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("MVComplex")
    app.setQuitOnLastWindowClosed(False)

    # Установка иконки
    icon_path = os.path.join(
        os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(__file__),
        "mvz-round.ico"
    )
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # Установка шрифта
    try:
        font = QFont("Segoe UI", 9)
        app.setFont(font)
    except Exception:
        pass

    # Создание главного окна
    window = MainWindow()
    window.show()

    _install_activation_server(window)

    log_boot("MVZ GUI shown.")
    exit_code = app.exec()
    log_boot(f"MVZ exit: {exit_code}")
    sys.exit(exit_code)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log_boot(f"UNHANDLED EXCEPTION: {traceback.format_exc()}")
        QMessageBox.critical(None, "Критическая ошибка", f"MVZ crashed:\n{e}")
        sys.exit(1)
