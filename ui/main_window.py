# ui/main_window.py
from __future__ import annotations

import os
import sys
import time
import shlex
import datetime
import subprocess
import json
import urllib.request
import urllib.error
import re
from subprocess import CREATE_NO_WINDOW
from typing import Optional, List, Tuple, Dict

from PySide6.QtCore import Qt, QTimer, QSettings, QProcess
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QProgressDialog,
    QStackedWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QSystemTrayIcon,
)


# --- Themes (обязательные функции по ТЗ) ---
try:
    from ui.themes import get_stylesheet, normalize_theme, THEME_ORDER, THEME_TITLES_RU
except Exception:
    def normalize_theme(name: str) -> str:
        return name if name in ("dark", "light", "purple", "toxic") else "dark"

    def get_stylesheet(name: str) -> str:
        return ""

    THEME_ORDER = ["dark", "light", "purple", "toxic"]
    THEME_TITLES_RU = {"dark": "Тёмная", "light": "Светлая", "purple": "Фиолетовая", "toxic": "Токсичная"}

# --- Optional deps ---
try:
    import winreg  # type: ignore
except Exception:
    winreg = None

try:
    import psutil  # type: ignore
except Exception:
    psutil = None

# --- Updater ---
try:
    # Твой файл называется ui/mvz_updater.py
    from ui.mvz_updater import apply_update_from_release
except ImportError:
    apply_update_from_release = None
    print("Ошибка: не найден файл ui/mvz_updater.py")
except Exception as e:
    apply_update_from_release = None
    print(f"Ошибка импорта апдейтера: {e}")


try:
    from discord_rpc import DiscordRPC, PYPRESENCE_AVAILABLE  # type: ignore
except Exception:
    DiscordRPC = None
    PYPRESENCE_AVAILABLE = False


APP_NAME = "MVZ"
SETTINGS_ORG = "MVZ"
SETTINGS_APP = "MVZapret"

UPDATE_OWNER = "MVComplex"
UPDATE_REPO = "MVZTEST"

# Обновление по GitHub Releases assets: manifest.json + update.zip
UPDATE_MANIFEST_ASSET = "manifest.json"

UPDATE_CHECK_URL = f"https://api.github.com/repos/{UPDATE_OWNER}/{UPDATE_REPO}/releases/latest"
UPDATE_USER_AGENT = "MVZ-Updater"
APP_VERSION = "1.5"


def resource_path(relative_path: str) -> str:
    try:
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def is_admin() -> bool:
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def ensure_hidden_console() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        SWHIDE = 0
        k32 = ctypes.windll.kernel32
        u32 = ctypes.windll.user32
        hwnd = k32.GetConsoleWindow()
        if hwnd:
            u32.ShowWindow(hwnd, SWHIDE)
    except Exception:
        pass


def _list_bat_files_near_app() -> List[str]:
    base = app_dir()
    dirs = [base, os.path.join(base, "ZZZ")]
    found: List[str] = []
    for d in dirs:
        try:
            if not os.path.isdir(d):
                continue
            for name in os.listdir(d):
                if name.lower().endswith(".bat"):
                    p = os.path.join(d, name)
                    if os.path.isfile(p):
                        found.append(os.path.abspath(p))
        except Exception:
            continue

    out: List[str] = []
    seen = set()
    for p in found:
        lp = p.lower()
        if lp not in seen:
            out.append(p)
            seen.add(lp)
    return out


def _bat_display_name(path: str) -> str:
    b = os.path.basename(path)
    parent = os.path.basename(os.path.dirname(path))
    if parent and parent.lower() == "zzz":
        return f"{b} (ZZZ)"
    return b


def _safe_split_cmdline_windows(line: str) -> List[str]:
    return shlex.split(line, posix=False)


def _merge_split_key_value_args(args: List[str]) -> List[str]:
    """
    Фикс типичных поломок shlex для winws аргументов:
    - '--wf-raw', 'tcp', 'DstPort', '=', '443' -> собираем обратно, если видим паттерны
    - 'key=', 'value' -> 'key=value' (важно для фильтров)
    - '--raw', 'something with spaces' (если батник дал раздельно) -> склеиваем аккуратно
    Это снижает шанс падения winws с ошибками по filter/raw. [file:1][file:2]
    """
    out: List[str] = []
    i = 0
    while i < len(args):
        a = args[i]

        # key=  value  -> key=value
        if a.endswith("=") and i + 1 < len(args):
            out.append(a + args[i + 1])
            i += 2
            continue

        # key = value -> key=value (редкий случай, но бывает если где-то стояли пробелы вокруг '=')
        if i + 2 < len(args) and args[i + 1] == "=":
            out.append(a + "=" + args[i + 2])
            i += 3
            continue

        out.append(a)
        i += 1

    return out


def parse_bat_variables_and_command(bat_path: str) -> Tuple[str, List[str], str]:
    bat_dir = os.path.abspath(os.path.dirname(bat_path))
    env: Dict[str, str] = {}

    def get_var(k: str) -> Optional[str]:
        return env.get(k.lower())

    def set_var(k: str, v: str) -> None:
        env[k.lower()] = v

    # базовые "бат" переменные
    set_var("dp0", bat_dir + "\\")
    set_var("~dp0", bat_dir + "\\")
    bin_dir = os.path.join(bat_dir, "bin")
    set_var("BIN", bin_dir if os.path.isdir(bin_dir) else bat_dir)

    # читаем .bat
    with open(bat_path, "r", encoding="utf-8", errors="ignore") as f:
        raw_lines = f.readlines()

    # склейка строк с ^
    lines: List[str] = []
    buf = ""
    for raw in raw_lines:
        s = raw.strip()
        if not s:
            continue
        low = s.lower()
        if low.startswith("rem ") or low.startswith("::") or low.startswith("@echo"):
            continue

        if s.endswith("^"):
            buf += s[:-1]
            continue

        buf += s
        lines.append(buf.strip())
        buf = ""

    if buf:
        lines.append(buf.strip())

    def safe_split_cmdline_windows(line: str) -> List[str]:
        return shlex.split(line, posix=False)

    def merge_split_key_value_args(args: List[str]) -> List[str]:
        # Склейка вида: ["--wf-tcp", "80,443"] -> ["--wf-tcp=80,443"]
        # и ["--wf-tcp=", "80,443"] -> ["--wf-tcp=80,443"]
        out: List[str] = []
        i = 0
        while i < len(args):
            a = args[i]

            # "--key=" + "value"
            if a.endswith("=") and i + 1 < len(args):
                out.append(a + args[i + 1])
                i += 2
                continue

            # "--key" + "value"  (если следующий токен не флаг)
            if a.startswith("-") and i + 1 < len(args) and not args[i + 1].startswith("-"):
                out.append(a + "=" + args[i + 1])
                i += 2
                continue

            out.append(a)
            i += 1
        return out

    def expand_vars(resolved: str) -> str:
        # быстрые замены бат-путей
        resolved = resolved.replace("%~dp0", bat_dir + "\\")
        resolved = resolved.replace("%dp0", bat_dir + "\\")
        resolved = resolved.replace("!dp0!", bat_dir + "\\")  # если вдруг

        # подстановка %VAR%
        for _ in range(15):
            if "%" not in resolved:
                break
            new_s = ""
            i = 0
            changed = False
            while i < len(resolved):
                if resolved[i] == "%":
                    j = resolved.find("%", i + 1)
                    if j != -1:
                        var = resolved[i + 1:j]
                        val = get_var(var)
                        if val is not None:
                            new_s += val
                            i = j + 1
                            changed = True
                            continue
                new_s += resolved[i]
                i += 1
            resolved = new_s
            if not changed:
                break

        return resolved

    # 1) ищем строку запуска winws.exe, параллельно собираем set-переменные
    winws_cmd_parts: Optional[List[str]] = None

    for ln in lines:
        resolved = expand_vars(ln)

        try:
            parts = safe_split_cmdline_windows(resolved)
        except ValueError:
            continue

        if not parts:
            continue

        cmd0 = parts[0].lower()

        # set A=B / set "A=B"
        if cmd0 == "set":
            remainder = resolved[3:].strip()
            if remainder.startswith('"') and remainder.endswith('"'):
                remainder = remainder[1:-1].strip()

            if "=" in remainder:
                k, v = remainder.split("=", 1)
                k, v = k.strip(), v.strip()
                if v.startswith('"') and v.endswith('"'):
                    v = v[1:-1]
                set_var(k, v)
            continue

        # нашли запуск winws
        if "winws.exe" in resolved.lower():
            winws_cmd_parts = parts
            break

    if not winws_cmd_parts:
        raise RuntimeError("В .bat не найдена команда запуска winws.exe")

    # 2) выделяем exe и args
    idx = -1
    for i, p in enumerate(winws_cmd_parts):
        if "winws.exe" in p.lower():
            idx = i
            break
    if idx == -1:
        raise RuntimeError("Не удалось выделить путь winws.exe из строки")

    exe_raw = winws_cmd_parts[idx].strip()
    raw_args = winws_cmd_parts[idx + 1:]

    exe = exe_raw
    if not os.path.isabs(exe):
        candidates = [
            os.path.join(bat_dir, exe),
            os.path.join(bat_dir, "bin", "winws.exe"),
            os.path.join(bat_dir, "winws.exe"),
            os.path.join(app_dir(), "bin", "winws.exe"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                exe = c
                break

    # 3) чистим/разворачиваем аргументы
    final_args: List[str] = []
    for arg in raw_args:
        clean = arg.replace("\\\\", "\\")
        clean = expand_vars(clean)  # <-- важно: разворачивает %~dp0 и %VAR% внутри аргументов

        # если после подстановок осталось что-то типа %GameFilter% — вырежем его из списков портов/значений
        # (иначе winws падает "bad value for --wf-tcp") [file:9]
        if "%" in clean and "=" in clean:
            key, val = clean.split("=", 1)
            # убираем "висячие" %VAR% только из значений-списков (через запятую)
            if "," in val:
                items = [x.strip() for x in val.split(",")]
                items = [x for x in items if not (x.startswith("%") and x.endswith("%")) and x != ""]
                val = ",".join(items)
                clean = key + "=" + val

        # подтягивание путей (hostlist/ipset/tls/quic/etc)
        if "=" in clean and any(k in clean for k in ("ipset", "hostlist", "fake", "tls", "quic", "pattern")):
            key, val = clean.split("=", 1)

            # если val пустое или это флаг — оставляем как есть
            if not val or val.startswith("-"):
                final_args.append(f"{key}={val}")
                continue

            # убираем кавычки вокруг пути
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val_unq = val[1:-1]
            else:
                val_unq = val

            if os.path.isfile(val_unq):
                # вернём в исходном виде (с кавычками или без)
                final_args.append(f"{key}={val_unq}")
                continue

            possible = [
                os.path.join(bat_dir, val_unq),
                os.path.join(bat_dir, "lists", val_unq),
                os.path.join(bat_dir, "bin", val_unq),
                os.path.join(app_dir(), val_unq),
                os.path.join(app_dir(), "lists", val_unq),
            ]
            found = None
            for p in possible:
                if os.path.isfile(p):
                    found = p
                    break

            final_args.append(f"{key}={found or val_unq}")
        else:
            final_args.append(clean)

    # 4) склейка "--key value" в "--key=value"
    final_args = merge_split_key_value_args(final_args)

    return exe, final_args, bat_dir


class MainWindow(QMainWindow):
    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    RUN_VALUE_NAME = "MVZ"

    def __init__(self) -> None:
        super().__init__()

        self.settings = QSettings(SETTINGS_ORG, SETTINGS_APP)

        # --- Best config (лучший .bat) ---
        # Храним последний лучший батник в настройках, чтобы был виден на главной/в тестах
        self.best_bat_name: str = self.settings.value("best_bat_name", "", type=str) or ""
        self._best_re = re.compile(r"^\s*Best config:\s*(.+?)\s*$")

        self.tests_process: QProcess | None = None

        # 0=ничего, 1=выбрали "Select test type", 2=выбрали "Select test run mode"
        self.tests_sent_choice = 0

        # Скрываем служебный текст и показываем только результаты Config:
        self.tests_show_results_only = False
        self.tests_in_results = False

        self.current_theme_name = normalize_theme(self.settings.value("theme", "dark"))
        self.selected_bat_path: str = self.settings.value("selected_bat_path", "", type=str) or ""

        self.winws_pid: Optional[int] = None
        self.winws_process: Optional[subprocess.Popen] = None
        self.detached_running = False
        self.session_start_time: Optional[datetime.datetime] = None

        self.really_quit = False
        self.net_optimized_once = False
        self.hires_timer_enabled = False

        self.discord_rpc = None

        self._ui_build()
        self._tray_build()

        # Таймеры (обязательные имена/методы)
        self.crash_check_timer = QTimer(self)
        self.crash_check_timer.setSingleShot(True)
        self.crash_check_timer.setInterval(2500)
        self.crash_check_timer.timeout.connect(self.checkstartupstatus)

        self.monitor_timer = QTimer(self)
        self.monitor_timer.setInterval(3000)
        self.monitor_timer.timeout.connect(self.poll_running)

        self.uptime_timer = QTimer(self)
        self.uptime_timer.setInterval(1000)
        self.uptime_timer.timeout.connect(self.update_uptime_footer)

        self.update_timer = QTimer(self)
        self.update_timer.setInterval(6 * 60 * 60 * 1000)
        self.update_timer.timeout.connect(self.check_updates_silent)

        # Init theme/logo/status
        self.apply_theme_by_name(self.current_theme_name)
        self.update_buttons(False)
        self.update_status_indicator(False)

        # Start timers
        self.uptime_timer.start()
        self.update_timer.start()
        QTimer.singleShot(5000, self.check_updates_silent)

        # Settings init (как у тебя было)
        self.refresh_bat_list_ui()

        autorun_bypass = self.settings.value("autorun_bypass", True, type=bool)  # True по умолчанию!
        self.autorun_cb.blockSignals(True)
        self.autorun_cb.setChecked(autorun_bypass)
        self.autorun_cb.setEnabled(self.is_autostart_enabled())
        self.autorun_cb.blockSignals(False)

        self._init_discord_like_original()

        # Автозапуск профиля при --autorun ИЛИ при включённой автозагрузке Windows
        if ("--autorun" in sys.argv and autorun_bypass) or self.is_autostart_enabled():
            QTimer.singleShot(1000, self.run_selected_profile)

    # ---------------- Best config helpers ----------------

    def set_best_bat(self, name: str) -> None:
        name = (name or "").strip()
        self.best_bat_name = name
        self.settings.setValue("best_bat_name", name)

        txt = f"Лучший профиль: {name}" if name else "Лучший профиль: —"

        lbl = getattr(self, "bestbat_home_lbl", None)
        if lbl is not None:
            lbl.setText(txt)

        lbl = getattr(self, "bestbat_tests_lbl", None)
        if lbl is not None:
            lbl.setText(txt)

    def try_parse_best_bat(self, line: str) -> None:
        """Поймать строку вида: Best config: xxx.bat"""
        if not line:
            return
        m = self._best_re.match(line)
        if m:
            self.set_best_bat(m.group(1))


    # ---------------- UI ----------------

    def _ui_build(self) -> None:
        self.setWindowTitle("MVZapret / MVZ")
        self.resize(1200, 750)

        icon_path = None
        for p in (
            resource_path("mvz-round.ico"),
            os.path.join(app_dir(), "mvz-round.ico"),
            os.path.join(os.path.dirname(__file__), "mvz-round.ico"),
        ):
            if os.path.isfile(p):
                icon_path = p
                break
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))

        root = QHBoxLayout()
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 16, 0, 16)
        side.setSpacing(0)

        logo_container = QWidget()
        logo_layout = QVBoxLayout(logo_container)
        logo_layout.setContentsMargins(0, 16, 0, 32)
        logo_layout.setSpacing(0)

        self.logo_label = QLabel()
        self.logo_label.setAlignment(Qt.AlignCenter)
        logo_layout.addWidget(self.logo_label, 0, Qt.AlignHCenter)
        side.addWidget(logo_container)

        self.btn_home = QPushButton("Главная")
        self.btn_settings = QPushButton("Настройки")
        self.btn_logs = QPushButton("Логи")
        self.btn_Tests = QPushButton("Тестирование")
        self.btn_info = QPushButton("Инфо")

        for b in (self.btn_home, self.btn_settings, self.btn_logs, self.btn_Tests, self.btn_info):
            b.setObjectName("Nav")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(48)
            side.addWidget(b)

        self.btn_home.setChecked(True)
        side.addStretch(1)

        self.pages = QStackedWidget()

        page_home = self.create_home_page()
        page_settings = self.create_settings_page()
        page_logs = self.create_logs_page()
        page_tests = self.create_tests_page()  # <-- ДОБАВИЛИ
        page_info = self.create_info_page()

        for w in (page_home, page_settings, page_logs, page_tests, page_info):  # <-- ДОБАВИЛИ
            self.pages.addWidget(w)

        root.addWidget(sidebar, 0)
        root.addWidget(self.pages, 1)

        self.btn_home.clicked.connect(lambda: self.switch_tab(0))
        self.btn_settings.clicked.connect(lambda: self.switch_tab(1))
        self.btn_logs.clicked.connect(lambda: self.switch_tab(2))
        self.btn_Tests.clicked.connect(lambda: self.switch_tab(3))
        self.btn_info.clicked.connect(lambda: self.switch_tab(4))

        self.run_btn.clicked.connect(self.run_selected_profile)
        self.stop_btn.clicked.connect(self.stop_winws)
        self.optimize_btn.clicked.connect(self.optimize_network)

    def create_home_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(12)

        # --- Title row ---
        title_row = QHBoxLayout()
        title = QLabel("MVZapret")
        title.setStyleSheet("font-size:24px;font-weight:700;")
        title_row.addWidget(title)
        title_row.addStretch()

        self.current_profile_label = QLabel("")
        self.current_profile_label.setStyleSheet("font-size:12px;color:#94A3B8;")
        title_row.addWidget(self.current_profile_label)

        lay.addLayout(title_row)

        # --- Best config label (из тестов) ---
        self.bestbat_home_lbl = QLabel()
        self.bestbat_home_lbl.setStyleSheet("font-size:16px;font-weight:700;color:#94A3B8;")
        self.bestbat_home_lbl.setText(
            f"Лучший профиль: {self.best_bat_name}" if (self.best_bat_name or "").strip() else "Лучший профиль: —"
        )
        lay.addWidget(self.bestbat_home_lbl)

        # --- Status row ---
        status_row = QHBoxLayout()
        status_row.setSpacing(12)

        self.status_indicator = QLabel()
        self.status_indicator.setFixedSize(20, 20)
        self.status_indicator.setStyleSheet(
            "background:#DC2626;border-radius:10px;border:2px solid #450A0A;"
        )

        self.status_label = QLabel("Остановлено")
        self.status_label.setStyleSheet("font-size:16px;font-weight:600;")

        status_row.addWidget(self.status_indicator)
        status_row.addWidget(self.status_label)
        status_row.addStretch()

        # --- Buttons row ---
        btns = QHBoxLayout()
        btns.setSpacing(16)

        self.run_btn = QPushButton("Запустить")
        self.run_btn.setObjectName("Action")
        self.run_btn.setCursor(Qt.PointingHandCursor)

        self.stop_btn = QPushButton("Остановить")
        self.stop_btn.setObjectName("Action")
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.setStyleSheet(
            "QPushButton{background:#EF4444;color:#FFF;border:none;border-radius:14px;"
            "padding:10px 22px;font-size:14px;font-weight:600;}"
            "QPushButton:hover{background:#DC2626;}"
            "QPushButton:disabled{background:#1F2933;color:#64748B;}"
        )

        btns.addWidget(self.run_btn)
        btns.addWidget(self.stop_btn)
        btns.addStretch()

        # --- Optimize button + priority label ---
        self.optimize_btn = QPushButton("Оптимизация пинга")
        self.optimize_btn.setObjectName("Action")
        self.optimize_btn.setCursor(Qt.PointingHandCursor)

        self.priority_label = QLabel("")
        self.priority_label.setStyleSheet("font-size:12px;")

        # ФУТЕР: "Время работы: HH:MM:SS" как ты просил
        footer = QHBoxLayout()
        footer.addStretch()
        self.uptime_footer = QLabel("Время работы: 00:00:00")
        self.uptime_footer.setStyleSheet("font-size:14px;font-weight:600;")
        footer.addWidget(self.uptime_footer)
        footer.addStretch()

        lay.addLayout(status_row)
        lay.addLayout(btns)
        lay.addWidget(self.optimize_btn)
        lay.addWidget(self.priority_label)
        lay.addStretch()
        lay.addLayout(footer)
        return page

    def create_settings_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(10)

        title = QLabel("Настройки")
        title.setStyleSheet("font-size:24px;font-weight:700;")
        lay.addWidget(title)

        self.autostart_cb = QCheckBox("Автозапуск MVZ при входе в Windows ")
        self.autostart_cb.setChecked(self.is_autostart_enabled())
        self.autostart_cb.toggled.connect(self.on_toggle_autostart)
        lay.addWidget(self.autostart_cb)

        self.autorun_cb = QCheckBox("Запускать обход сразу после старта MVZ")
        lay.addWidget(self.autorun_cb)
        self.autorun_cb.toggled.connect(self.on_toggle_autorun)

        self.discord_rpc_cb = QCheckBox("Discord Rich Presence")
        self.discord_rpc_cb.toggled.connect(self.on_toggle_discord_rpc)
        lay.addWidget(self.discord_rpc_cb)

        # ---- ВЫБОР ПРОФИЛЯ (.bat) ----
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Профиль (.bat):"))

        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(320)
        self.profile_combo.currentIndexChanged.connect(self.on_profile_changed)
        profile_row.addWidget(self.profile_combo, 1)
        lay.addLayout(profile_row)

        # Theme row (как было)
        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Тема:"))

        self.theme_combo = QComboBox()
        self.theme_combo.addItems([THEME_TITLES_RU.get(t, t) for t in THEME_ORDER])
        theme_to_index = {name: i for i, name in enumerate(THEME_ORDER)}
        self.theme_combo.setCurrentIndex(theme_to_index.get(self.current_theme_name, 0))
        self.theme_combo.currentIndexChanged.connect(self.on_theme_changed)
        theme_row.addWidget(self.theme_combo, 1)

        lay.addLayout(theme_row)
        lay.addStretch()
        return page

    def create_logs_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(16)

        title = QLabel("Логи")
        title.setStyleSheet("font-size:24px;font-weight:700;")
        self.log = QTextEdit()
        self.log.setReadOnly(True)

        lay.addWidget(title)
        lay.addWidget(self.log, 1)
        return page

    def create_tests_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(16)

        title = QLabel("Тестирование")
        title.setStyleSheet("font-size:24px;font-weight:700;")
        lay.addWidget(title)

        # Лучший профиль (обновляется через set_best_bat())
        self.bestbat_tests_lbl = QLabel()
        self.bestbat_tests_lbl.setStyleSheet("font-size:16px;font-weight:700;color:#94A3B8;")
        best_name = (getattr(self, "best_bat_name", "") or "").strip()
        self.bestbat_tests_lbl.setText(f"Лучший профиль: {best_name}" if best_name else "Лучший профиль: —")
        lay.addWidget(self.bestbat_tests_lbl)  # <-- ВОТ ЭТОГО НЕ ХВАТАЛО

        # Кнопки управления
        row = QHBoxLayout()
        row.setSpacing(16)

        self.btn_tests_start = QPushButton("Запустить тестирование")
        self.btn_tests_start.setObjectName("Action")
        self.btn_tests_start.clicked.connect(self.start_tests)

        self.btn_tests_stop = QPushButton("Остановить")
        self.btn_tests_stop.setObjectName("Action")
        self.btn_tests_stop.setEnabled(False)
        self.btn_tests_stop.clicked.connect(self.stop_tests)

        row.addWidget(self.btn_tests_start)
        row.addWidget(self.btn_tests_stop)
        row.addStretch(1)
        lay.addLayout(row)

        # Вывод теста
        self.tests_chat = QTextEdit()
        self.tests_chat.setReadOnly(True)
        self.tests_chat.setPlaceholderText("Вывод теста будет здесь…")
        lay.addWidget(self.tests_chat, 1)

        return page

    def create_info_page(self) -> QWidget:
        """
        Возвращаю страницу Инфо как в твоём старом варианте: карточки + ссылки + версия. [file:1]
        """
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(20)

        title = QLabel("Инфо")
        title.setStyleSheet("font-size:24px;font-weight:700;")
        lay.addWidget(title)

        self.info_cards: List[QFrame] = []
        self.info_titles: List[QLabel] = []
        self.info_links: List[Tuple[QLabel, str]] = []

        def link_card(title_text: str, url: str) -> QFrame:
            card = QFrame()
            card.setProperty("class", "InfoCard")
            l = QVBoxLayout(card)
            l.setSpacing(8)

            t = QLabel(title_text)
            t.setProperty("class", "InfoTitle")

            lk = QLabel()
            lk.setProperty("class", "InfoLink")
            lk.setOpenExternalLinks(True)
            lk.setTextInteractionFlags(Qt.TextBrowserInteraction)

            self.info_cards.append(card)
            self.info_titles.append(t)
            self.info_links.append((lk, url))

            l.addWidget(t)
            l.addWidget(lk)
            return card

        lay.addWidget(link_card("Сайт проекта", "https://mvcomplexsite.github.io"))
        lay.addWidget(link_card("Telegram", "https://t.me/motyait2"))

        lay.addStretch()

        ver_row = QHBoxLayout()
        ver_row.addStretch()
        ver = QLabel(f"Version: {APP_VERSION}")
        ver.setStyleSheet("color:#64748B;font-size:12px;")
        ver_row.addWidget(ver)
        ver_row.addStretch()
        lay.addLayout(ver_row)

        self.apply_info_theme()
        return page

    # Вставь этот блок ВНУТРИ class MainWindow(QMainWindow):
    # (на одном уровне с create_tests_page / run_selected_profile / stop_winws)

    def _tests_append(self, s: str) -> None:
        # Не падаем, если UI ещё не создан или вкладка не открыта
        w = getattr(self, "tests_chat", None)
        if w is None:
            return
        try:
            w.append(s)
        except Exception:
            pass

    def _tests_set_running_ui(self, running: bool) -> None:
        # Не падаем, если кнопки ещё не созданы
        b1 = getattr(self, "btn_tests_start", None)
        b2 = getattr(self, "btn_tests_stop", None)
        if b1 is not None:
            b1.setEnabled(not running)
        if b2 is not None:
            b2.setEnabled(running)

    def _tests_ps1_path(self) -> str:
        # mvz.exe рядом с папкой utils
        return os.path.join(app_dir(), "utils", "test zapret.ps1")

    def _powershell_exe(self) -> str:
        # Надёжнее, чем просто "powershell" (PATH может быть поломан)
        if os.name == "nt":
            p = os.path.join(
                os.environ.get("SystemRoot", r"C:\Windows"),
                "System32",
                "WindowsPowerShell",
                "v1.0",
                "powershell.exe",
            )
            if os.path.isfile(p):
                return p
        return "powershell"

    def start_tests(self) -> None:
        # Если уже запущено
        proc_now = getattr(self, "tests_process", None) or getattr(self, "testsprocess", None)
        if proc_now is not None and proc_now.state() != QProcess.NotRunning:
            return

        # --- Сброс состояния (и новое, и старое имя) ---
        self.tests_sent_choice = 0
        self.testssentchoice = 0  # мост на старый код
        self.tests_in_results = False
        self.testsinresults = False  # мост на старый код

        ps1 = os.path.abspath(self._tests_ps1_path())
        if not os.path.isfile(ps1):
            QMessageBox.critical(self, "Тестирование", f"Не найден файл:\n{ps1}")
            self._tests_set_running_ui(False)
            self.tests_process = None
            self.testsprocess = None
            return

        if not is_admin():
            QMessageBox.warning(self, "Тестирование", "Запусти MVZ от имени администратора и повтори.")
            self._tests_set_running_ui(False)
            self.tests_process = None
            self.testsprocess = None
            return

        # Чистим чат (и мост на старое имя виджета)
        if getattr(self, "tests_chat", None) is not None:
            self.tests_chat.clear()
            self.testschat = self.tests_chat  # мост, если где-то используется self.testschat
        elif getattr(self, "testschat", None) is not None:
            self.testschat.clear()
            self.tests_chat = self.testschat  # мост в обратную сторону

        self._tests_append("=== Старт тестирования ===")
        self._tests_append(f"PS1: {ps1}")
        self._tests_append("Подготовка теста... Первые результаты появятся позже (когда начнутся строки Config:).")

        p = QProcess(self)

        # --- ВАЖНО: сохраняем процесс сразу в два атрибута ---
        self.tests_process = p
        self.testsprocess = p

        p.setProcessChannelMode(QProcess.MergedChannels)

        # Подавляем консольное окно на Windows
        if os.name == "nt":
            try:
                def _modifier(args):
                    args.flags |= 0x08000000  # CREATE_NO_WINDOW

                p.setCreateProcessArgumentsModifier(_modifier)
            except Exception:
                pass

        # Подключаемся к тому обработчику, который реально существует в твоём коде
        handler = getattr(self, "_tests_read_output", None) or getattr(self, "testsreadoutput", None)
        if handler is not None:
            # Лучше readyRead (ловит любые данные), но оставим и StandardOutput для совместимости
            p.readyRead.connect(handler)
            p.readyRead.connect(self._tests_read_output)

        p.finished.connect(getattr(self, "_tests_finished", None) or getattr(self, "testsfinished", lambda *_: None))
        p.errorOccurred.connect(getattr(self, "_tests_error", None) or getattr(self, "testserror", lambda *_: None))

        p.setWorkingDirectory(os.path.dirname(ps1))
        p.start(self._powershell_exe(), ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1])

        if not p.waitForStarted(3000):
            self._tests_append(f"[ERR] PowerShell не запустился: {p.errorString()}")
            self._tests_set_running_ui(False)
            self.tests_process = None
            self.testsprocess = None
            return

        def _safe_write(payload: bytes) -> None:
            proc = getattr(self, "tests_process", None) or getattr(self, "testsprocess", None)
            if proc is None or proc.state() == QProcess.NotRunning:
                return
            try:
                proc.write(payload)
                proc.waitForBytesWritten(500)
            except Exception:
                pass

        # Насильно прожимаем оба меню (test type и run mode)
        QTimer.singleShot(400, lambda: _safe_write(b"1\r\n"))
        QTimer.singleShot(900, lambda: _safe_write(b"1\r\n"))

        self._tests_set_running_ui(True)

    def _tests_error(self, err) -> None:
        self._tests_append(f"=== Ошибка запуска теста: {err} ===")
        self._tests_set_running_ui(False)
        self.tests_process = None

    def _tests_read_output(self) -> None:
        p = self.tests_process
        if p is None:
            return

        # При MergedChannels лучше читать ВСЁ, а не только stdout
        data = bytes(p.readAll())
        if not data:
            return

        try:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    text = data.decode("cp866")
                except UnicodeDecodeError:
                    text = data.decode("cp1251", errors="replace")

            # Автовыбор 1) test type -> 1
            if self.tests_sent_choice < 1 and (
                    "Select test type" in text
                    or "Select test type:" in text
                    or "1 Standard tests" in text
                    or "[1] Standard tests" in text
            ):
                try:
                    p.write(b"1\r\n")  # важно: Enter
                    p.waitForBytesWritten(500)
                    self.tests_sent_choice = 1
                except Exception:
                    pass

            # Автовыбор 2) run mode -> 1
            if self.tests_sent_choice < 2 and (
                    "Select test run mode" in text
                    or "Select test run mode:" in text
                    or "1 All configs" in text
                    or "[1] All configs" in text
            ):
                try:
                    p.write(b"1\r\n")  # важно: Enter
                    p.waitForBytesWritten(500)
                    self.tests_sent_choice = 2
                except Exception:
                    pass

            for line in text.splitlines():
                self.try_parse_best_bat(line)
                self._tests_append(line)

        except Exception as e:
            # Чтобы больше не было "висит и молчит" из-за падения слота
            self._tests_append(f"[ERR] _tests_read_output crashed: {e!r}")

    def _tests_finished(self, exit_code: int, exit_status) -> None:
        self._tests_append(f"=== Завершено: code={exit_code} ===")
        self._tests_set_running_ui(False)
        self.tests_process = None

    def stop_tests(self) -> None:
        p = self.tests_process
        if p is None:
            return

        self._tests_append("=== Остановка... ===")
        p.terminate()
        QTimer.singleShot(1500, self._tests_kill_if_alive)

    def _tests_kill_if_alive(self) -> None:
        p = self.tests_process
        if p is None:
            return
        if p.state() != QProcess.NotRunning:
            p.kill()

    # ---------------- Profiles (.bat) ----------------

    def refresh_bat_list_ui(self) -> None:
        bats = _list_bat_files_near_app()

        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()

        if not bats:
            self.profile_combo.addItem("Не найдено .bat (положи рядом с MVZ)", "")
            self.profile_combo.setEnabled(False)
            self.selected_bat_path = ""
            self.settings.setValue("selected_bat_path", "")
        else:
            self.profile_combo.setEnabled(True)
            for p in bats:
                self.profile_combo.addItem(_bat_display_name(p), p)

            idx = 0
            if self.selected_bat_path:
                for i in range(self.profile_combo.count()):
                    if (self.profile_combo.itemData(i) or "").lower() == self.selected_bat_path.lower():
                        idx = i
                        break
            self.profile_combo.setCurrentIndex(idx)
            self.selected_bat_path = self.profile_combo.itemData(idx) or ""
            self.settings.setValue("selected_bat_path", self.selected_bat_path)

        self.profile_combo.blockSignals(False)
        self.update_profile_labels()

    def update_profile_labels(self) -> None:
        if self.selected_bat_path:
            self.current_profile_label.setText(_bat_display_name(self.selected_bat_path))
        else:
            self.current_profile_label.setText("Профиль не выбран")

    def on_profile_changed(self, index: int) -> None:
        new_path = self.profile_combo.itemData(index) or ""
        if not new_path:
            self.selected_bat_path = ""
            self.settings.setValue("selected_bat_path", "")
            self.update_profile_labels()
            return

        if os.path.abspath(new_path).lower() != os.path.abspath(self.selected_bat_path or "").lower():
            self.append_log(f"[MVZ] Смена профиля: {_bat_display_name(new_path)}")
            # обязательное требование: при смене профиля стопаем winws и пишем Остановлено. [file:1]
            self.stop_winws()
            self.selected_bat_path = new_path
            self.settings.setValue("selected_bat_path", self.selected_bat_path)
            self.update_profile_labels()

    # ---------------- Run/Stop ----------------

    def run_selected_profile(self) -> None:
        ensure_hidden_console()

        bat_Path = self.selected_bat_path or ""
        if not bat_Path or not os.path.isfile(bat_Path):
            QMessageBox.critical(self, APP_NAME, f"Не найден .bat профиль:\n{bat_Path or '(не выбран)'}")
            self.update_buttons(False)
            self.update_status_indicator(False)
            return

        # Убиваем хвосты прошлых запусков
        self.kill_running_instances(note=False)

        batdir = os.path.abspath(os.path.dirname(bat_Path))
        self.append_log(f"[MVZ] RUN BAT: {_bat_display_name(bat_Path)}")

        try:
            # Доп. способ спрятать окно (иногда надёжнее, чем только CREATENOWINDOW)
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0  # SW_HIDE

            # Запуск .bat через cmd.exe без окна:
            proc = subprocess.Popen(
                ["cmd.exe", "/d", "/c", "call", bat_Path],
                cwd=batdir,
                creationflags=CREATE_NO_WINDOW,
                startupinfo=si,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,  # если будут зависания — можно временно заменить на subprocess.DEVNULL
            )

            self.append_log(f"[MVZ] CMD PID: {proc.pid}")

        except Exception as e:
            self.append_log(f"[MVZ] BAT RUN ERR: {e}")
            self.update_buttons(False)
            self.update_status_indicator(False)
            return

        # proc — это cmd.exe; winws.exe стартует внутри него
        self.winws_process = proc
        self.winws_pid = None  # позже привяжем PID winws.exe

        self.detached_running = True
        self.session_start_time = datetime.datetime.now()

        self.update_buttons(True)
        self.update_status_indicator(True)

        self.monitor_timer.start()
        self.crash_check_timer.start()

        # Привязка PID winws.exe (обязательно включить)
        QTimer.singleShot(800, self._bind_winws_pid_after_bat)

        if self.tray.supportsMessages():
            self.tray.showMessage(APP_NAME, "Профиль запущен", QSystemTrayIcon.Information, 2500)

        #self.optimize_network_silent()
        self.enable_hires_timer(True)

    def stop_winws(self) -> None:
        self.kill_running_instances(note=False)
        self.detached_running = False
        self.monitor_timer.stop()
        self.crash_check_timer.stop()

        self.update_buttons(False)
        self.update_status_indicator(False)
        self.enable_hires_timer(False)

        if self.tray.supportsMessages():
            self.tray.showMessage(APP_NAME, "Остановлено", QSystemTrayIcon.Warning, 2000)

    # ---------------- Process helpers ----------------

    def kill_by_name(self, name: str) -> None:
        if os.name != "nt":
            return
        try:
            subprocess.run(
                ["taskkill", "/IM", name, "/F", "/T"],
                creationflags=CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=4,
            )
        except Exception:
            pass

    def kill_by_pid(self, pid: int) -> None:
        if os.name != "nt":
            return
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F", "/T"],
                creationflags=CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=4,
            )
        except Exception:
            pass

    def kill_running_instances(self, note: bool = True) -> None:
        if self.winws_pid:
            try:
                self.kill_by_pid(self.winws_pid)
            except Exception:
                pass

        try:
            self.kill_by_name("winws.exe")
        except Exception:
            pass

        self.winws_pid = None
        self.winws_process = None

        if note:
            self.append_log("[MVZ] winws.exe остановлен")

    def _pid_alive(self, pid: Optional[int]) -> bool:
        if not pid or pid <= 0:
            return False

        if psutil is not None:
            try:
                return psutil.pid_exists(pid) and psutil.Process(pid).is_running()
            except Exception:
                return False

        if os.name != "nt":
            return False

        try:
            out = subprocess.check_output(
                ["cmd", "/c", f'tasklist /FI "PID eq {pid}"'],
                creationflags=CREATE_NO_WINDOW,
            ).decode("utf-8", errors="replace")
            return str(pid) in out
        except Exception:
            return False

    def is_running_now(self) -> bool:
        if self.winws_pid and self._pid_alive(self.winws_pid):
            return True

        if self.winws_process is not None:
            try:
                return self.winws_process.poll() is None
            except Exception:
                pass

        if os.name == "nt":
            try:
                out = subprocess.check_output(
                    ["cmd", "/c", 'tasklist /FI "IMAGENAME eq winws.exe"'],
                    creationflags=CREATE_NO_WINDOW,
                ).decode("utf-8", errors="replace")
                return "winws.exe" in out.lower()
            except Exception:
                return False

        return False

    def _bind_winws_pid_after_bat(self) -> None:
        if psutil is None:
            return
        if self.winws_process is None:
            return

        try:
            cmd_pid = int(self.winws_process.pid)
        except Exception:
            return

        try:
            for p in psutil.process_iter(["pid", "name", "ppid"]):
                name = (p.info.get("name") or "").lower()
                ppid = int(p.info.get("ppid") or 0)
                if name == "winws.exe" and ppid == cmd_pid:
                    self.winws_pid = int(p.info["pid"])
                    self.append_log(f"[MVZ] WINWS PID: {self.winws_pid}")

                    # если есть функция поднятия приоритета — вызывай тут
                    try:
                        self.boost_winws_priority()
                    except Exception:
                        pass

                    break
        except Exception:
            pass

    # ---------------- Timers slots ----------------

    def checkstartupstatus(self) -> None:
        proc = self.winws_process

        # 1) Если процесс (cmd/winws) уже завершился — читаем stderr и показываем
        if proc is not None:
            try:
                rc = proc.poll()
            except Exception:
                rc = None

            if rc is not None:
                # cmd.exe мог уже завершиться, но winws.exe ещё работает — тогда это НЕ ошибка
                try:
                    if self.winws_pid and self.pid_alive(self.winws_pid):
                        return
                except Exception:
                    pass

                raw = b""
                try:
                    if proc.stderr:
                        raw = proc.stderr.read(32768) or b""  # <= максимум 32KB, не висим навечно
                except Exception:
                    raw = b""

                err_output = raw.decode("utf-8", errors="replace").strip()
                if "�" in err_output:
                    err_output = raw.decode("cp866", errors="replace").strip()
                if "�" in err_output:
                    err_output = raw.decode("cp1251", errors="replace").strip()

                try:
                    self.append_log(f"[MVZ] winws завершился (code={rc})")
                    if err_output:
                        self.append_log("[MVZ] stderr:")
                        self.append_log(err_output)
                except Exception:
                    pass

                # стопаем всё, даже если stderr пустой
                try:
                    self.stop_winws()
                except Exception:
                    pass

                if err_output:
                    try:
                        QMessageBox.critical(self, "winws", f"winws завершился с ошибкой:\n{err_output}")
                    except Exception:
                        pass
                return

        # 2) Если по факту winws не найден в системе — считаем, что старт не удался
        try:
            running = self.is_running_now()
        except Exception:
            running = False

        if not running:
            try:
                self.append_log("[MVZ] winws не запущен (после старта)")
            except Exception:
                pass
            try:
                self.stop_winws()
            except Exception:
                pass

    def poll_running(self) -> None:
        running = self.is_running_now()
        if running != self.detached_running:
            self.detached_running = running
            self.update_buttons(running)
            self.update_status_indicator(running)
            self.append_log("[MVZ] Запущено" if running else "[MVZ] Остановлено")
            self.enable_hires_timer(running)

        if not running:
            self.monitor_timer.stop()

    def update_uptime_footer(self) -> None:
        if not hasattr(self, "uptime_footer") or self.uptime_footer is None:
            return

        if not self.is_running_now():
            self.uptime_footer.setText("Время работы: 00:00:00")
            return

        if psutil is not None and self.winws_pid and self._pid_alive(self.winws_pid):
            try:
                p = psutil.Process(self.winws_pid)
                ct = datetime.datetime.fromtimestamp(p.create_time())
                up = datetime.datetime.now() - ct
                self.uptime_footer.setText(f"Время работы: {str(up).split('.')[0]}")
                return
            except Exception:
                pass

        if self.session_start_time:
            up = datetime.datetime.now() - self.session_start_time
            self.uptime_footer.setText(f"Время работы: {str(up).split('.')[0]}")
        else:
            self.uptime_footer.setText("Время работы: 00:00:00")

    # ================== АВТООБНОВЛЕНИЕ (FIXED) ==================

    def _version_tuple(self, v: str) -> tuple[int, int, int]:
        """Превращает '1.5.0' в (1, 5, 0) для сравнения"""
        s = (v or "").strip()
        if not s: return (0, 0, 0)
        s = s.split()[0].strip()
        if s.lower().startswith("v"): s = s[1:]
        for sep in ("-", "+"):
            if sep in s: s = s.split(sep, 1)[0]
        parts = s.split(".")
        out = []
        for p in parts:
            try:
                out.append(int(p))
            except:
                out.append(0)
        while len(out) < 3: out.append(0)
        return tuple(out[:3])

    def check_updates_silent(self) -> None:
        self.append_log(f"[Update] check start app={APP_VERSION}")

        try:
            req = urllib.request.Request(
                UPDATE_CHECK_URL,
                headers={"User-Agent": UPDATE_USER_AGENT},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode("utf-8", errors="replace"))

            tag = (data.get("tag_name") or "").strip()
            self.append_log(f"[Update] latest tag={tag!r}")
            if not tag:
                self.append_log("[Update] no tag_name in release/latest")
                return

            # 1. ПРОВЕРКА ВЕРСИИ
            # Если версия на сервере <= текущей, ничего не делаем
            if self._version_tuple(tag) <= self._version_tuple(APP_VERSION):
                self.append_log(f"[Update] up-to-date (installed: {APP_VERSION})")
                return

            assets = data.get("assets") or []
            # names = [a.get("name") for a in assets]
            # self.append_log(f"[Update] assets={names}")

            has_manifest = any(a.get("name") == UPDATE_MANIFEST_ASSET for a in assets)
            if not has_manifest:
                self.append_log(f"[Update] missing asset {UPDATE_MANIFEST_ASSET}")
                return

            if apply_update_from_release is None:
                self.append_log("[Update] updater not available (apply_update_from_release is None)")
                return

            self.append_log("[Update] update available -> Showing dialog")

            # 2. ПОКАЗЫВАЕМ ДИАЛОГ
            changelog = data.get("body") or ""
            self.show_update_dialog(tag, changelog)

        except urllib.error.HTTPError as e:
            self.append_log(f"[Update] HTTP error {e.code}")
        except Exception as e:
            self.append_log(f"[Update] Exception {e}")

    def show_update_dialog(self, version: str, changelog: str) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Обновление MVZ {version}")
        dialog.setFixedSize(500, 400)

        layout = QVBoxLayout(dialog)

        # Заголовок
        lbl = QLabel(f"Доступна новая версия: {version}")
        lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: #22c55e;")
        layout.addWidget(lbl)

        # Лог изменений
        box = QTextBrowser()
        # Превращаем переносы строк в <br> для HTML
        html_log = (changelog or "").replace("\n", "<br>")
        box.setHtml(html_log)
        layout.addWidget(box)

        info = QLabel("При нажатии 'Обновить' приложение перезапустится.")
        info.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(info)

        # Кнопки
        btns = QHBoxLayout()
        btn_yes = QPushButton("Обновить")
        btn_yes.setCursor(Qt.PointingHandCursor)
        btn_yes.setObjectName("Action")  # Чтобы кнопка была зеленой
        btn_yes.clicked.connect(lambda: self.start_update_process(dialog))

        btn_no = QPushButton("Позже")
        btn_no.setCursor(Qt.PointingHandCursor)
        btn_no.clicked.connect(dialog.reject)

        btns.addWidget(btn_yes)
        btns.addWidget(btn_no)
        layout.addLayout(btns)

        dialog.exec()

    def start_update_process(self, dialog: QDialog) -> None:
        dialog.accept()
        # Показываем полоску прогресса
        progress = QProgressDialog("Загрузка обновления...", "Отмена", 0, 100, self)
        progress.setWindowTitle("MVZ Updater")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()

        try:
            self.download_and_update(progress)
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "Ошибка", f"Ошибка обновления:\n{e}")

    def download_and_update(self, progress_dialog: QProgressDialog) -> None:
        if apply_update_from_release is None:
            return

        def progress_cb(label, percent):
            progress_dialog.setLabelText(label)
            progress_dialog.setValue(int(percent))
            QApplication.processEvents()

        def stop_bin_cb():
            # Останавливаем winws перед заменой файлов
            try:
                # Используем твой метод остановки
                self.stop_winws()
            except:
                pass

        # Запускаем апдейтер
        res = apply_update_from_release(
            owner=UPDATE_OWNER,
            repo=UPDATE_REPO,
            current_version=APP_VERSION,
            manifest_name=UPDATE_MANIFEST_ASSET,
            user_agent=UPDATE_USER_AGENT,
            allow_internal=True,
            progress=progress_cb,
            stop_bin_cb=stop_bin_cb,
            settings=self.settings
        )

        progress_dialog.close()

        # Определяем, нужно ли перезагружаться
        should_restart = False

        if res:
            # Если вернулся dict
            if isinstance(res, dict):
                if res.get("updatedany") or res.get("restarted"):
                    should_restart = True
            # Если вернулся объект
            else:
                upd = getattr(res, "updatedany", False)
                rst = getattr(res, "restarted", False)
                if upd or rst:
                    should_restart = True

            # Если res не пустой, но флаги не проставились (на всякий случай)
            if not should_restart and res is not None:
                should_restart = True

        if should_restart:
            # 1. Ставим флаг настоящего выхода (чтобы обойти трей/защиту от закрытия)
            self.reallyquit = True

            # 2. Отключаем Discord RPC
            try:
                if hasattr(self, 'discord_rpc') and self.discord_rpc:
                    self.discord_rpc.disconnect()
            except:
                pass

            # 3. Закрываем окна Qt
            QApplication.closeAllWindows()
            QApplication.quit()

            # 4. ЖЕСТКИЙ ВЫХОД (гарантирует закрытие процесса для апдейтера)
            import os
            os._exit(0)
        else:
            QMessageBox.information(self, "MVZ", "Обновление не потребовалось или уже установлено.")

    # ---------------- Theme / Logo / Info theme ----------------

    def apply_theme_by_name(self, name: str) -> None:
        name = normalize_theme(name)
        self.current_theme_name = name
        self.setStyleSheet(get_stylesheet(name))
        self.settings.setValue("theme", name)
        self.update_logo_by_theme()
        self.apply_info_theme()

    def update_logo_by_theme(self) -> None:
        if not hasattr(self, "logo_label") or self.logo_label is None:
            return

        base_names: List[str] = []
        if self.current_theme_name == "toxic":
            base_names.extend(["toxic.png", "mvz_logo_toxic.png", "mvzlogo_toxic.png"])
        base_names.extend(["mvz_logo.png", "mvzlogo.png", "logo.png", "mvz.png"])

        search_dirs = [
            app_dir(),
            os.path.join(app_dir(), "assets"),
            os.path.join(app_dir(), "ui", "assets"),
            os.path.join(os.path.dirname(__file__), "assets"),
        ]

        candidates: List[str] = []
        for n in base_names:
            candidates.append(resource_path(n))
            candidates.append(resource_path(os.path.join("assets", n)))
            candidates.append(resource_path(os.path.join("ui", "assets", n)))
            for d in search_dirs:
                candidates.append(os.path.join(d, n))

        pix = None
        for p in candidates:
            try:
                if os.path.isfile(p):
                    tp = QPixmap(p)
                    if not tp.isNull():
                        pix = tp
                        break
            except Exception:
                continue

        if pix:
            self.logo_label.setPixmap(pix.scaled(200, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.logo_label.setText("")
            self.logo_label.setStyleSheet("")
        else:
            self.logo_label.setPixmap(QPixmap())
            color = "#39ff14" if self.current_theme_name == "toxic" else "#60A5FA"
            self.logo_label.setText("MVZ")
            self.logo_label.setStyleSheet(f"font-size:28px;color:{color};font-weight:700;")

    def apply_info_theme(self) -> None:
        if not hasattr(self, "info_cards"):
            return

        toxic = self.current_theme_name == "toxic"
        if toxic:
            card_ss = (
                "QFrame{background: rgba(0, 20, 0, 0.70);border: 2px solid #39ff14;"
                "border-radius:16px;padding:20px;}"
                "QFrame:hover{border-color:#ccffcc;background: rgba(57,255,20,0.10);}"
            )
            title_ss = "color:#ccffcc;font-size:18px;font-weight:700;"
            link_tpl = '<a href="{url}" style="color:#39ff14;text-decoration:none;">{url}</a>'
        else:
            card_ss = (
                "QFrame{background: rgba(76,29,149,0.6);border:2px solid #7C3AED;"
                "border-radius:16px;padding:20px;}"
                "QFrame:hover{border-color:#A855F7;background: rgba(129,140,248,0.15);}"
            )
            title_ss = "color:#F9FAFB;font-size:18px;font-weight:700;"
            link_tpl = '<a href="{url}" style="color:#C4B5FD;text-decoration:none;">{url}</a>'

        for card in self.info_cards:
            card.setStyleSheet(card_ss)
        for lbl in self.info_titles:
            lbl.setStyleSheet(title_ss)
        for lbl, url in self.info_links:
            lbl.setText(link_tpl.format(url=url))

    def on_theme_changed(self, index: int) -> None:
        if index < 0 or index >= len(THEME_ORDER):
            return
        self.apply_theme_by_name(THEME_ORDER[index])

    # ---------------- Status/UI helpers ----------------

    def switch_tab(self, idx: int) -> None:
        self.pages.setCurrentIndex(idx)
        self.btn_home.setChecked(idx == 0)
        self.btn_settings.setChecked(idx == 1)
        self.btn_logs.setChecked(idx == 2)
        self.btn_Tests.setChecked(idx == 3)
        self.btn_info.setChecked(idx == 4)

    def update_buttons(self, running: bool) -> None:
        self.run_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.optimize_btn.setEnabled(running)

    def update_status_indicator(self, running: bool) -> None:
        if running:
            self.status_indicator.setStyleSheet("background:#10B981;border-radius:10px;border:2px solid #064E3B;")
            self.status_label.setText("Запущено")
            self.tray.setToolTip("MVZ - Запущено")
        else:
            self.status_indicator.setStyleSheet("background:#DC2626;border-radius:10px;border:2px solid #450A0A;")
            self.status_label.setText("Остановлено")
            self.tray.setToolTip("MVZ - Остановлено")

    def append_log(self, s: str) -> None:
        if not hasattr(self, "log") or self.log is None:
            return
        try:
            if self.log.document().blockCount() > 1000:
                cursor = self.log.textCursor()
                cursor.movePosition(cursor.Start)
                cursor.movePosition(cursor.Down, cursor.KeepAnchor, 100)
                cursor.removeSelectedText()
            self.log.append(s)
        except Exception:
            pass

    # ---------------- Tray ----------------

    def _tray_build(self) -> None:
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(self.windowIcon())
        self.tray.activated.connect(self.on_tray_activated)

        tray_menu = QMenu(self)
        tray_menu.addAction(QAction("Открыть MVZ", self, triggered=self.show_main_from_tray))
        tray_menu.addSeparator()
        tray_menu.addAction(QAction("Запустить", self, triggered=self.run_selected_profile))
        tray_menu.addAction(QAction("Остановить", self, triggered=self.stop_winws))
        tray_menu.addSeparator()

        self.act_autostart = QAction("Автозапуск", self, checkable=True)
        self.act_autostart.setChecked(self.is_autostart_enabled())
        self.act_autostart.toggled.connect(self.set_autostart_enabled)
        tray_menu.addAction(self.act_autostart)

        tray_menu.addSeparator()
        tray_menu.addAction(QAction("Выход", self, triggered=self.exit_from_tray))

        self.tray.setContextMenu(tray_menu)
        self.tray.show()

    def show_main_from_tray(self) -> None:
        self.showNormal()
        self.activateWindow()
        try:
            self.raise_()
        except Exception:
            pass

    def on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_main_from_tray()

    def exit_from_tray(self) -> None:
        self.really_quit = True
        try:
            self.enable_hires_timer(False)
        except Exception:
            pass
        QApplication.quit()

    def closeEvent(self, event) -> None:
        if not self.really_quit and self.tray and self.tray.isVisible():
            self.hide()
            event.ignore()
            return
        event.accept()

    # ---------------- Autostart (HKCU Run) ----------------

    def base_autostart_command(self) -> str:
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}"'
        py_dir = os.path.dirname(sys.executable)
        pythonw = os.path.join(py_dir, "pythonw.exe")
        script = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "main.py"))
        if os.path.isfile(pythonw):
            return f'"{pythonw}" "{script}"'
        return f'"{sys.executable}" "{script}"'

    def autostart_command(self) -> str:
        cmd = self.base_autostart_command()
        autorun = self.settings.value("autorun_bypass", False, type=bool)
        if autorun:
            cmd += " --autorun"
        return cmd

    def read_run_value(self) -> Optional[str]:
        if os.name != "nt" or winreg is None:
            return None
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.RUN_KEY, 0, winreg.KEY_READ) as k:
                val, _ = winreg.QueryValueEx(k, self.RUN_VALUE_NAME)
                return val if isinstance(val, str) else None
        except FileNotFoundError:
            return None
        except OSError:
            return None

    def is_autostart_enabled(self) -> bool:
        return bool(self.read_run_value())

    def write_run_value(self, cmd: str) -> bool:
        if os.name != "nt" or winreg is None:
            return False
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.RUN_KEY) as k:
                winreg.SetValueEx(k, self.RUN_VALUE_NAME, 0, winreg.REG_SZ, cmd)
            return True
        except OSError:
            return False

    def delete_run_value(self) -> bool:
        if os.name != "nt" or winreg is None:
            return False
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                try:
                    winreg.DeleteValue(k, self.RUN_VALUE_NAME)
                except FileNotFoundError:
                    pass
            return True
        except OSError:
            return False

    def set_autostart_enabled(self, enable: bool) -> None:
        ok = self.write_run_value(self.autostart_command()) if enable else self.delete_run_value()
        if not ok and os.name == "nt":
            self.append_log("[MVZ] Не удалось изменить автозапуск в реестре")

        st = self.is_autostart_enabled()

        self.autostart_cb.blockSignals(True)
        self.autostart_cb.setChecked(st)
        self.autostart_cb.blockSignals(False)

        self.act_autostart.blockSignals(True)
        self.act_autostart.setChecked(st)
        self.act_autostart.blockSignals(False)

        self.autorun_cb.setEnabled(st)

    def on_toggle_autostart(self, checked: bool) -> None:
        self.set_autostart_enabled(checked)
        self.append_log("[MVZ] Автозапуск включён" if checked else "[MVZ] Автозапуск выключен")

    def on_toggle_autorun(self, checked: bool) -> None:
        self.settings.setValue("autorun_bypass", checked)
        if self.is_autostart_enabled():
            self.write_run_value(self.autostart_command())
        self.append_log("[MVZ] --autorun включён" if checked else "[MVZ] --autorun выключен")

    # ---------------- Discord (как в твоём старом стиле) ----------------

    def _init_discord_like_original(self) -> None:
        enabled = self.settings.value("discord_rpc_enabled", True, type=bool)
        if PYPRESENCE_AVAILABLE and DiscordRPC is not None:
            self.discord_rpc_cb.setEnabled(True)
            self.discord_rpc_cb.blockSignals(True)
            self.discord_rpc_cb.setChecked(enabled)
            self.discord_rpc_cb.blockSignals(False)
        else:
            self.discord_rpc_cb.setEnabled(False)
            self.discord_rpc_cb.blockSignals(True)
            self.discord_rpc_cb.setChecked(False)
            self.discord_rpc_cb.blockSignals(False)
            self.settings.setValue("discord_rpc_enabled", False)

    def on_toggle_discord_rpc(self, enabled: bool) -> None:
        self.settings.setValue("discord_rpc_enabled", enabled)

    # ---------------- Network optimization ----------------

    def optimize_network(self) -> None:
        if not is_admin():
            QMessageBox.warning(self, APP_NAME, "Нужны права администратора для оптимизации сети.")
            return
        self.apply_netsh_settings(verbose=True)
        if self.priority_label is not None:
            self.priority_label.setText("Оптимизация сети применена.")

    def optimize_network_silent(self) -> None:
        if self.net_optimized_once:
            return
        self.net_optimized_once = True
        if is_admin():
            self.apply_netsh_settings(verbose=False)

    def apply_netsh_settings(self, verbose: bool) -> None:
        if os.name != "nt":
            return
        cmds = [
            ["netsh", "int", "tcp", "set", "global", "ecncapability=disabled"],
            ["netsh", "int", "tcp", "set", "global", "autotuninglevel=normal"],
            ["netsh", "int", "tcp", "set", "global", "rss=enabled"],
            ["netsh", "int", "tcp", "set", "global", "rsc=enabled"],
            ["netsh", "int", "tcp", "set", "supplemental", "template=internet", "congestionprovider=cubic"],
            ["ipconfig", "/flushdns"],
        ]
        ok_all = True
        for args in cmds:
            try:
                p = subprocess.run(
                    args,
                    creationflags=CREATE_NO_WINDOW,
                    stdout=subprocess.PIPE if verbose else subprocess.DEVNULL,
                    stderr=subprocess.STDOUT if verbose else subprocess.DEVNULL,
                    timeout=7,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                if verbose and p.stdout:
                    out = p.stdout.strip()
                    if out:
                        self.append_log(f"[NET] {' '.join(args)} -> {out}")
                if p.returncode != 0:
                    ok_all = False
            except Exception:
                ok_all = False
        if verbose:
            self.append_log("[NET] OK" if ok_all else "[NET] Есть ошибки при применении")

    def boost_winws_priority(self) -> None:
        if psutil is None:
            return
        try:
            if self.winws_pid and self._pid_alive(self.winws_pid):
                psutil.Process(self.winws_pid).nice(psutil.HIGH_PRIORITY_CLASS)
                self.append_log("[MVZ] winws.exe priority HIGH")
        except Exception:
            pass

    def enable_hires_timer(self, enable: bool) -> None:
        if os.name != "nt":
            return
        try:
            import ctypes
            winmm = ctypes.WinDLL("winmm")
            if enable and not self.hires_timer_enabled:
                winmm.timeBeginPeriod(1)
                self.hires_timer_enabled = True
                self.append_log("[MVZ] Hi-res timer: 1ms ON")
            if (not enable) and self.hires_timer_enabled:
                winmm.timeEndPeriod(1)
                self.hires_timer_enabled = False
                self.append_log("[MVZ] Hi-res timer: OFF")
        except Exception:
            pass
