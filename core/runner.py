from __future__ import annotations

import os
import subprocess
from subprocess import CREATE_NO_WINDOW
from typing import Callable, Optional, List

from core.profiles_builtin import get_profile_by_id


def _default_winws_paths(base_dir: str) -> dict:
    bin_dir = os.path.join(base_dir, "bin")
    return {
        "base_dir": base_dir,
        "bin_dir": bin_dir,
        "winws": os.path.join(bin_dir, "winws.exe"),
    }


def start_winws_profile(
    profile_id: str,
    base_dir: str,
    on_line: Optional[Callable[[str], None]] = None,
) -> int:
    """
    Синхронный запуск winws.exe с аргументами профиля.
    Возвращает код выхода winws.exe.
    """
    base_dir = os.path.abspath(base_dir)
    paths = _default_winws_paths(base_dir)
    exe = paths["winws"]

    if not os.path.isfile(exe):
        if on_line:
            on_line(f"[MVZ] Не найден winws.exe: {exe}")
        return 1

    profile = get_profile_by_id(profile_id)
    args: List[str] = profile.args_factory(base_dir)

    if not args:
        if on_line:
            on_line(f"[MVZ] Профиль «{profile.name}» не настроен: нет аргументов запуска.")
            on_line("[MVZ] Перенесите аргументы из соответствующего .bat в profiles_builtin.py.")
        return 2

    proc = subprocess.Popen(
        [exe] + args,
        cwd=base_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=CREATE_NO_WINDOW,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if proc.stdout:
        for line in proc.stdout:
            if on_line:
                on_line(line.rstrip("\r\n"))

    return proc.wait()


def spawn_winws_profile_detached(profile_id: str, base_dir: str) -> subprocess.Popen:
    """
    Асинхронный запуск winws.exe напрямую (без .bat, без wscript/vbs).
    Возвращает Popen (можно взять pid).
    """
    base_dir = os.path.abspath(base_dir)
    paths = _default_winws_paths(base_dir)
    exe = paths["winws"]

    profile = get_profile_by_id(profile_id)
    args: List[str] = profile.args_factory(base_dir)

    if not os.path.isfile(exe):
        raise FileNotFoundError(exe)

    if not args:
        raise RuntimeError(f"Profile '{profile.name}' has no args configured.")

    return subprocess.Popen(
        [exe] + args,
        cwd=base_dir,
        creationflags=CREATE_NO_WINDOW,
    )
