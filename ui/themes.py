# ui/themes.py
from __future__ import annotations

from typing import Dict, List

# Вынесенные стили из ui/main_window.py (как ты и прислал)

DARK_STYLESHEET = """
QMainWindow { background: #0F172A; }
QFrame#Sidebar { background: #020617; border-right: 1px solid #1E293B; min-width: 220px; max-width: 220px; }

QPushButton[objectName="Nav"] {
    background: transparent; color: #9CA3AF; border: none; border-radius: 10px;
    padding: 10px 14px; text-align: left; font-size: 14px; font-weight: 500; margin: 4px 10px;
}
QPushButton[objectName="Nav"]:hover { background: rgba(59,130,246,0.12); color: #BFDBFE; }
QPushButton[objectName="Nav"]:checked {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #2563EB, stop:1 #0EA5E9);
    color: #FFFFFF; font-weight: 600;
}

QPushButton[objectName="Action"] {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #22C55E, stop:1 #16A34A);
    color: #F9FAFB; border: none; border-radius: 14px; padding: 10px 22px;
    font-size: 14px; font-weight: 600; min-width: 150px;
}
QPushButton[objectName="Action"]:hover {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #4ADE80, stop:1 #22C55E);
}
QPushButton[objectName="Action"]:pressed { background: #15803D; }
QPushButton[objectName="Action"]:disabled { background: #1F2933; color: #64748B; }

QCheckBox { color: #CBD5E1; spacing: 8px; font-size: 13px; }
QCheckBox::indicator {
    width: 18px; height: 18px; border-radius: 4px;
    border: 2px solid #475569; background: #020617;
}
QCheckBox::indicator:hover { border-color: #64748B; }
QCheckBox::indicator:checked { background: #1D4ED8; border-color: #60A5FA; }

QTextEdit {
    background: #020617; color: #E2E8F0; border: 1px solid #1F2937;
    border-radius: 12px; padding: 10px; font-size: 13px; selection-background-color: #2563EB;
}
QComboBox {
    background: #020617; color: #E5E7EB; border: 1px solid #1F2937;
    border-radius: 10px; padding: 6px 32px 6px 10px; font-size: 13px;
}
QComboBox:hover { border-color: #3B82F6; }

QLabel { color: #E2E8F0; }
QTextBrowser { background: #0F172A; color: #E2E8F0; border: 1px solid #1E293B; border-radius: 8px; }

/* Info cards (по умолчанию фиолетовая стилистика, как было) */
QFrame[class="InfoCard"] {
    background: rgba(76,29,149,0.6);
    border: 2px solid #7C3AED;
    border-radius: 16px;
    padding: 20px;
}
QFrame[class="InfoCard"]:hover {
    border-color: #A855F7;
    background: rgba(129,140,248,0.15);
}
QLabel[class="InfoTitle"] { color: #F9FAFB; font-size: 18px; font-weight: 700; }
QLabel[class="InfoLink"] { color: #C4B5FD; }
QLabel[class="InfoLink"] a { color: #C4B5FD; text-decoration: none; }
"""

LIGHT_STYLESHEET = """
QMainWindow { background: #F9FAFB; }
QFrame#Sidebar { background: #EFF2F7; border-right: 1px solid #D1D5DB; min-width: 220px; max-width: 220px; }

QPushButton[objectName="Nav"] {
    background: transparent; color: #4B5563; border: none; border-radius: 10px;
    padding: 10px 14px; text-align: left; font-size: 14px; font-weight: 500; margin: 4px 10px;
}
QPushButton[objectName="Nav"]:hover { background: #E0F2FE; color: #1D4ED8; }
QPushButton[objectName="Nav"]:checked { background: #2563EB; color: #FFFFFF; font-weight: 600; }

QPushButton[objectName="Action"] {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #3B82F6, stop:1 #2563EB);
    color: #FFFFFF; border: none; border-radius: 14px; padding: 10px 22px;
    font-size: 14px; font-weight: 600; min-width: 150px;
}
QPushButton[objectName="Action"]:hover {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #60A5FA, stop:1 #3B82F6);
}
QPushButton[objectName="Action"]:pressed { background: #1D4ED8; }
QPushButton[objectName="Action"]:disabled { background: #E5E7EB; color: #9CA3AF; }

QCheckBox { color: #111827; spacing: 8px; font-size: 13px; }
QCheckBox::indicator {
    width: 18px; height: 18px; border-radius: 4px;
    border: 2px solid #9CA3AF; background: #F9FAFB;
}
QCheckBox::indicator:hover { border-color: #6B7280; }
QCheckBox::indicator:checked { background: #3B82F6; border-color: #1D4ED8; }

QTextEdit {
    background: #FFFFFF; color: #111827; border: 1px solid #D1D5DB;
    border-radius: 12px; padding: 10px; font-size: 13px;
}
QComboBox {
    background: #FFFFFF; color: #111827; border: 1px solid #D1D5DB;
    border-radius: 10px; padding: 6px 32px 6px 10px; font-size: 13px;
}
QComboBox:hover { border-color: #3B82F6; }

QLabel { color: #111827; }
QTextBrowser { background: #FFFFFF; color: #111827; border: 1px solid #D1D5DB; border-radius: 8px; }

/* Info cards (как было) */
QFrame[class="InfoCard"] {
    background: rgba(76,29,149,0.6);
    border: 2px solid #7C3AED;
    border-radius: 16px;
    padding: 20px;
}
QFrame[class="InfoCard"]:hover {
    border-color: #A855F7;
    background: rgba(129,140,248,0.15);
}
QLabel[class="InfoTitle"] { color: #F9FAFB; font-size: 18px; font-weight: 700; }
QLabel[class="InfoLink"] { color: #C4B5FD; }
QLabel[class="InfoLink"] a { color: #C4B5FD; text-decoration: none; }
"""

PURPLE_STYLESHEET = """
QMainWindow { background: #050816; }
QFrame#Sidebar { background: #0B1020; border-right: 1px solid #4C1D95; min-width: 220px; max-width: 220px; }

QPushButton[objectName="Nav"] {
    background: transparent; color: #C4B5FD; border: none; border-radius: 10px;
    padding: 10px 14px; text-align: left; font-size: 14px; font-weight: 500; margin: 4px 10px;
}
QPushButton[objectName="Nav"]:hover { background: rgba(129,140,248,0.18); color: #E0E7FF; }
QPushButton[objectName="Nav"]:checked {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #7C3AED, stop:1 #6366F1);
    color: #FFFFFF; font-weight: 600;
}

QPushButton[objectName="Action"] {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #8B5CF6, stop:1 #6366F1);
    color: #F9FAFB; border: none; border-radius: 14px; padding: 10px 22px;
    font-size: 14px; font-weight: 600; min-width: 150px;
}
QPushButton[objectName="Action"]:hover {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #A855F7, stop:1 #818CF8);
}
QPushButton[objectName="Action"]:pressed { background: #4C1D95; }
QPushButton[objectName="Action"]:disabled { background: #111827; color: #6B7280; }

QCheckBox { color: #E5E7EB; spacing: 8px; font-size: 13px; }
QCheckBox::indicator {
    width: 18px; height: 18px; border-radius: 4px;
    border: 2px solid #4C1D95; background: #020617;
}
QCheckBox::indicator:hover { border-color: #7C3AED; }
QCheckBox::indicator:checked { background: #7C3AED; border-color: #C4B5FD; }

QTextEdit {
    background: #020617; color: #E5E7EB; border: 1px solid #312E81;
    border-radius: 12px; padding: 10px; font-size: 13px; selection-background-color: #6366F1;
}
QComboBox {
    background: #020617; color: #E5E7EB; border: 1px solid #312E81;
    border-radius: 10px; padding: 6px 32px 6px 10px; font-size: 13px;
}
QComboBox:hover { border-color: #7C3AED; }

QLabel { color: #E5E7EB; }
QTextBrowser { background: #050816; color: #E5E7EB; border: 1px solid #4C1D95; border-radius: 8px; }

/* Info cards (фиолетовая стилистика) */
QFrame[class="InfoCard"] {
    background: rgba(76,29,149,0.6);
    border: 2px solid #7C3AED;
    border-radius: 16px;
    padding: 20px;
}
QFrame[class="InfoCard"]:hover {
    border-color: #A855F7;
    background: rgba(129,140,248,0.15);
}
QLabel[class="InfoTitle"] { color: #F9FAFB; font-size: 18px; font-weight: 700; }
QLabel[class="InfoLink"] { color: #C4B5FD; }
QLabel[class="InfoLink"] a { color: #C4B5FD; text-decoration: none; }
"""

TOXIC_STYLESHEET = """
/* Главное окно с градиентом */
QMainWindow {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #051a05, stop:1 #0a290a);
}

/* Сайдбар (полупрозрачный) */
QFrame#Sidebar {
    background: rgba(0, 20, 0, 0.85);
    border-right: 2px solid #39ff14;
    min-width: 220px;
    max-width: 220px;
}

/* Кнопки навигации */
QPushButton[objectName="Nav"] {
    background: transparent;
    color: #39ff14;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 10px 14px;
    text-align: left;
    font-size: 14px;
    font-family: "Consolas", monospace;
    font-weight: 700;
    margin: 4px 10px;
}
QPushButton[objectName="Nav"]:hover {
    background: rgba(57, 255, 20, 0.15);
    border: 1px solid #39ff14;
    color: #ccffcc;
}
QPushButton[objectName="Nav"]:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #39ff14, stop:1 #00cc00);
    color: #000000;
    border: 1px solid #39ff14;
    font-weight: 900;
}

/* Кнопки действий */
QPushButton[objectName="Action"] {
    background: #000000;
    color: #39ff14;
    border: 2px solid #39ff14;
    border-radius: 14px;
    padding: 10px 22px;
    font-size: 14px;
    font-weight: 800;
    font-family: "Consolas", monospace;
    min-width: 150px;
}
QPushButton[objectName="Action"]:hover { background: #39ff14; color: #000000; }
QPushButton[objectName="Action"]:pressed { background: #00cc00; border-color: #00cc00; }
QPushButton[objectName="Action"]:disabled { border-color: #1a4d1a; color: #1a4d1a; background: transparent; }

/* Чекбоксы */
QCheckBox { color: #39ff14; spacing: 8px; font-size: 13px; font-family: "Consolas"; }
QCheckBox::indicator {
    width: 18px; height: 18px;
    border-radius: 4px;
    border: 2px solid #39ff14;
    background: #000000;
}
QCheckBox::indicator:hover { background: rgba(57, 255, 20, 0.3); }
QCheckBox::indicator:checked { background: #39ff14; border-color: #39ff14; image: url(none); }

/* Текстовые поля и логи */
QTextEdit {
    background: rgba(0, 0, 0, 0.6);
    color: #39ff14;
    border: 1px solid #39ff14;
    border-radius: 12px;
    padding: 10px;
    font-family: "Consolas";
    font-size: 12px;
    selection-background-color: #39ff14;
    selection-color: #000000;
}

/* Выпадающие списки */
QComboBox {
    background: #000000;
    color: #39ff14;
    border: 1px solid #39ff14;
    border-radius: 10px;
    padding: 6px 32px 6px 10px;
    font-family: "Consolas";
}
QComboBox:hover { background: rgba(57, 255, 20, 0.1); }
QComboBox QAbstractItemView {
    background: #000000;
    color: #39ff14;
    selection-background-color: #39ff14;
    selection-color: #000000;
}

/* Лейблы */
QLabel { color: #ccffcc; font-family: "Segoe UI", sans-serif; }

/* Текст в диалогах обновления */
QTextBrowser {
    background: rgba(0, 0, 0, 0.6);
    color: #39ff14;
    border: 1px solid #39ff14;
    border-radius: 8px;
}

/* Info cards (TOXIC) */
QFrame[class="InfoCard"] {
    background: rgba(0, 20, 0, 0.70);
    border: 2px solid #39ff14;
    border-radius: 16px;
    padding: 20px;
}
QFrame[class="InfoCard"]:hover {
    border-color: #ccffcc;
    background: rgba(57, 255, 20, 0.10);
}
QLabel[class="InfoTitle"] { color: #ccffcc; font-size: 18px; font-weight: 700; }
QLabel[class="InfoLink"] { color: #39ff14; }
QLabel[class="InfoLink"] a { color: #39ff14; text-decoration: none; }
"""


THEMES: Dict[str, str] = {
    "dark": DARK_STYLESHEET,
    "light": LIGHT_STYLESHEET,
    "purple": PURPLE_STYLESHEET,
    "toxic": TOXIC_STYLESHEET,
}

THEME_ORDER: List[str] = ["dark", "light", "purple", "toxic"]

THEME_TITLES_RU: Dict[str, str] = {
    "dark": "Тёмная",
    "light": "Светлая",
    "purple": "Фиолетовая",
    "toxic": "Токсичная",
}


def normalize_theme(theme_name: str) -> str:
    return theme_name if theme_name in THEMES else "dark"


def get_stylesheet(theme_name: str) -> str:
    return THEMES.get(normalize_theme(theme_name), DARK_STYLESHEET)
