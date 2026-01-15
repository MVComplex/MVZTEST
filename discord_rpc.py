"""
Discord Rich Presence интеграция для MVZ
Требует pypresence: pip install pypresence
"""
import time
import datetime
from typing import Optional
try:
    from pypresence import Presence
    PYPRESENCE_AVAILABLE = True
except ImportError:
    PYPRESENCE_AVAILABLE = False
    Presence = None

class DiscordRPC:
    # Client ID вашего Discord Application
    CLIENT_ID = "1423685786309628015"

    def __init__(self):
        self.rpc: Optional[Presence] = None
        self.connected = False
        self.start_time = None

    def connect(self) -> bool:
        """Подключение к Discord RPC"""
        if not PYPRESENCE_AVAILABLE:
            print("[Discord RPC] pypresence не установлен")
            return False
        if self.connected:
            print("[Discord RPC] Уже подключено")
            return True
        try:
            print(f"[Discord RPC] Попытка подключения с Client ID: {self.CLIENT_ID}")
            self.rpc = Presence(self.CLIENT_ID)
            self.rpc.connect()
            self.connected = True
            self.start_time = int(time.time())
            print("[Discord RPC] Успешно подключено!")
            return True
        except Exception as e:
            print(f"[Discord RPC] Ошибка подключения: {e}")
            print("[Discord RPC] Убедитесь что:")
            print("  1. Discord запущен и полностью загружен")
            print("  2. В настройках Discord включено 'Display current activity'")
            print("  3. Client ID правильный (из Discord Developer Portal)")
            self.connected = False
            return False

    def disconnect(self):
        """Отключение от Discord RPC"""
        if self.rpc and self.connected:
            try:
                self.rpc.close()
                print("[Discord RPC] Отключено")
            except Exception as e:
                print(f"[Discord RPC] Ошибка при отключении: {e}")
        self.connected = False
        self.rpc = None
        self.start_time = None

    def update_idle(self):
        """Обновление статуса: приложение запущено, но winws остановлен"""
        if not self.connected or not self.rpc:
            print("[Discord RPC] Не подключено, пропуск update_idle")
            return
        try:
            print("[Discord RPC] Обновление статуса: Остановлен")
            self.rpc.update(
                state="Остановлен",
                details="MVZapret - DPI Bypass",
                start=self.start_time
            )
        except Exception as e:
            print(f"[Discord RPC] Ошибка обновления (idle): {e}")

    def update_running(self, profile_name: str = "ALT2", session_start: Optional[datetime.datetime] = None):
        """Обновление статуса: winws запущен"""
        if not self.connected or not self.rpc:
            print("[Discord RPC] Не подключено, пропуск update_running")
            return
        try:
            start_timestamp = int(session_start.timestamp()) if session_start else self.start_time
            print(f"[Discord RPC] Обновление статуса: Активен ({profile_name})")

            self.rpc.update(
                state=f"Профиль: {profile_name}",
                details="Активен - обход блокировок",
                start=start_timestamp,
                buttons=[
                    {"label": "Discord", "url": "https://discord.gg/RtQ8fYnP8p"},
                    {"label": "Telegram", "url": "https://t.me/motyait2"}
                ]
            )
        except Exception as e:
            print(f"[Discord RPC] Ошибка обновления (running): {e}")

    def clear(self):
        """Очистка Rich Presence (убрать статус полностью)"""
        if not self.connected or not self.rpc:
            return
        try:
            self.rpc.clear()
            print("[Discord RPC] Статус очищен")
        except Exception:
            pass
