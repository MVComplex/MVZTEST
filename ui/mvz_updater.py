from __future__ import annotations

import os
import sys
import json
import time
import ssl
import hashlib
import shutil
import tempfile
import zipfile
import subprocess
from pathlib import PurePosixPath
from dataclasses import dataclass
from typing import Optional, Callable, Any

import urllib.request
import urllib.error

ProgressCb = Callable[[str, int], None]


@dataclass
class UpdateResult:
    updated_any: bool
    restarted: bool
    changed_files: list[str]
    new_version: str


LOG_PATH = os.path.join(tempfile.gettempdir(), "mvz_updater.log")


def _log(msg: str) -> None:
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_PATH, "a", encoding="utf-8", errors="ignore") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


# === ПОЛНОЕ ОТКЛЮЧЕНИЕ SSL ПРОВЕРКИ ===
# Создаём глобальный контекст БЕЗ проверки сертификатов
_SSL_CONTEXT = ssl._create_unverified_context()


def _urlopen(req: urllib.request.Request, timeout: int):
    """Все запросы идут через этот контекст (без проверки SSL)."""
    return urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT)


def app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _safe_rel_path(rel: str) -> str:
    rel = (rel or "").replace("\\", "/").lstrip("/")
    p = PurePosixPath(rel)
    if p.is_absolute() or ".." in p.parts or (len(p.parts) > 0 and ":" in p.parts[0]):
        raise ValueError(f"Bad path: {rel}")
    return str(p)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_copy_replace(src: str, dst: str) -> None:
    dst_dir = os.path.dirname(dst)
    if dst_dir:
        os.makedirs(dst_dir, exist_ok=True)
    tmp = dst + ".tmp"
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except:
                pass


def http_get_json(url: str, user_agent: str, timeout: int = 15) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with _urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def find_asset_url(release: dict, asset_name: str) -> Optional[str]:
    for a in release.get("assets", []) or []:
        if a.get("name") == asset_name:
            return a.get("browser_download_url")
    return None


def download_url_to_file(
        url: str, dst_path: str, user_agent: str, timeout: int = 120,
        progress: Optional[ProgressCb] = None, label: str = ""
) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with _urlopen(req, timeout=timeout) as response:
        total = int(response.headers.get("Content-Length", 0) or 0)
        downloaded = 0
        if progress:
            progress(label, 0)

        dst_dir = os.path.dirname(dst_path)
        if dst_dir:
            os.makedirs(dst_dir, exist_ok=True)

        with open(dst_path, "wb") as f:
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if progress and total > 0:
                    pct = int((downloaded / total) * 100)
                    progress(label, max(0, min(100, pct)))
        if progress:
            progress(label, 100)


def load_manifest(path: str) -> dict:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        m = json.load(f)
    if not isinstance(m, dict):
        raise ValueError("manifest.json: root must be dict")
    if "files" not in m or not isinstance(m["files"], list):
        raise ValueError("manifest.json: missing 'files' list")
    if "delete" in m and not isinstance(m.get("delete", []), list):
        raise ValueError("manifest.json: 'delete' must be list")
    return m


def _dedupe_keep_order(items: list[str]) -> list[str]:
    out, seen = [], set()
    for x in items:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out


def compute_changed_files(manifest: dict, base_dir: str) -> list[str]:
    changed = []
    for item in manifest.get("files", []) or []:
        if not isinstance(item, dict):
            continue
        rel = item.get("path")
        sha = (item.get("sha256") or "").lower().strip()
        if not rel or not sha:
            continue
        rel = _safe_rel_path(rel)
        local = os.path.join(base_dir, rel)
        if not os.path.isfile(local):
            changed.append(rel)
            continue
        try:
            if sha256_file(local).lower() != sha:
                changed.append(rel)
        except:
            changed.append(rel)
    return _dedupe_keep_order(changed)


def compute_delete_files(manifest: dict, base_dir: str) -> list[str]:
    deleted = []
    for rel in manifest.get("delete", []) or []:
        if not isinstance(rel, str):
            continue
        rel = _safe_rel_path(rel)
        target = os.path.join(base_dir, rel)
        if os.path.exists(target):
            deleted.append(rel)
    return _dedupe_keep_order(deleted)


def extract_needed_from_zip(zip_path: str, needed_paths: list[str], out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    needed_paths = [_safe_rel_path(p) for p in needed_paths]
    with zipfile.ZipFile(zip_path, "r") as z:
        names = set(z.namelist())
        for rel in needed_paths:
            real_name = rel if rel in names else ("./" + rel)
            if real_name not in names and rel not in names:
                raise RuntimeError(f"update.zip missing file: {rel}")
            use_name = real_name if real_name in names else rel
            out_path = os.path.join(out_dir, rel)
            os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
            with z.open(use_name, "r") as src, open(out_path, "wb") as dst:
                shutil.copyfileobj(src, dst)


def needs_deferred(rel: str, exe_name: str, allow_internal: bool) -> bool:
    p = rel.replace("\\", "/").lower()
    exe = exe_name.replace("\\", "/").lower()
    return p == exe or (allow_internal and p.startswith("_internal/"))


def build_deferred_bat(
        app_dir_path: str, stage_dir: str, deferred_files: list[str],
        deferred_deletes: list[str], exe_name: str, allow_internal: bool
) -> str:
    tmp_dir = tempfile.gettempdir()
    bat_path = os.path.join(tmp_dir, "MVZ_update_files.bat")
    exe_basename = os.path.basename(exe_name)

    def norm(p: str) -> str:
        return p.replace("\\", "/").lower()

    has_internal = allow_internal and any(norm(p).startswith("_internal/") for p in deferred_files)
    has_exe = any(norm(p) == norm(exe_name) for p in deferred_files)

    lines = [
        "@echo off", "chcp 65001 >nul", "setlocal",
        f"set APPDIR={app_dir_path}", f"set STAGE={stage_dir}", "",
        ":wait_loop",
        f'tasklist /FI "IMAGENAME eq {exe_basename}" 2>NUL | find /I "{exe_basename}" >NUL',
        "if not errorlevel 1 ( timeout /t 1 /nobreak >nul & goto wait_loop )", ""
    ]

    for rel in deferred_deletes:
        lines.append(f'del /f /q "%APPDIR%\\{rel.replace("/", chr(92))}" >nul 2>nul')

    if has_internal:
        lines.append(
            'if exist "%STAGE%\\_internal" robocopy "%STAGE%\\_internal" "%APPDIR%\\_internal" /E /NFL /NDL /NJH /NJS /NP >nul')

    if has_exe:
        lines.append(
            f'if exist "%STAGE%\\{exe_basename}" copy /y "%STAGE%\\{exe_basename}" "%APPDIR%\\{exe_basename}" >nul')

    for rel in deferred_files:
        if norm(rel) == norm(exe_name) or (allow_internal and norm(rel).startswith("_internal/")):
            continue
        wrel = rel.replace("/", "\\")
        d = os.path.dirname(wrel)
        if d:
            lines.append(f'mkdir "%APPDIR%\\{d}" >nul 2>nul')
        lines.append(f'copy /y "%STAGE%\\{wrel}" "%APPDIR%\\{wrel}" >nul')

    lines.extend([
        f'start "" "%APPDIR%\\{exe_basename}"',
        'rmdir /s /q "%STAGE%" >nul 2>nul',
        'del "%~f0" >nul 2>nul',
        "endlocal"
    ])

    with open(bat_path, "w", encoding="utf-8", errors="ignore") as f:
        f.write("\r\n".join(lines))
    return bat_path


def _version_tuple(v: str) -> tuple[int, ...]:
    s = (v or "").strip().lstrip("v").split("-")[0].split("+")[0]
    return tuple(int(p) if p.isdigit() else 0 for p in (s.split(".") + ["0"] * 3)[:3])


def apply_update_from_release(
        owner: str, repo: str, current_version: str,
        manifest_name: str = "manifest.json", user_agent: str = "MVZ-Updater",
        allow_internal: bool = False, progress: Optional[ProgressCb] = None,
        stop_bin_cb: Optional[Callable[[], None]] = None, settings: Optional[Any] = None
) -> UpdateResult:
    base_dir = app_dir()
    _log(f"[Update] check start (app={current_version})")

    try:
        latest = http_get_json(
            f"https://api.github.com/repos/{owner}/{repo}/releases/latest",
            user_agent, timeout=15
        )
    except Exception as e:
        _log(f"[Update] Exception: {repr(e)}")
        raise

    tag = (latest.get("tag_name") or "").strip()
    if not tag or _version_tuple(tag) <= _version_tuple(current_version):
        return UpdateResult(False, False, [], tag)

    manifest_url = find_asset_url(latest, manifest_name)
    if not manifest_url:
        return UpdateResult(False, False, [], tag)

    exe_name = os.path.basename(sys.executable) if getattr(sys, "frozen", False) else "MVZ.exe"
    tmp_dir = tempfile.gettempdir()
    manifest_path = os.path.join(tmp_dir, "mvz_manifest.json")
    stage_dir = os.path.join(tmp_dir, "mvz_update_stage")
    zip_path = os.path.join(tmp_dir, "mvz_update.zip")

    if os.path.isdir(stage_dir):
        shutil.rmtree(stage_dir, ignore_errors=True)

    download_url_to_file(manifest_url, manifest_path, user_agent, timeout=60, progress=progress, label=manifest_name)
    manifest = load_manifest(manifest_path)

    package_name = (manifest.get("package") or "update.zip").strip() or "update.zip"
    package_url = find_asset_url(latest, package_name)
    if not package_url:
        return UpdateResult(False, False, [], tag)

    changed = compute_changed_files(manifest, base_dir)
    deletes = compute_delete_files(manifest, base_dir)
    touched = _dedupe_keep_order(changed + deletes)

    if not touched:
        if settings:
            try:
                settings.setValue("last_release_tag", tag)
            except:
                pass
        return UpdateResult(False, False, [], tag)

    if stop_bin_cb:
        try:
            stop_bin_cb()
        except:
            pass

    imm_del, def_del = [], []
    for r in deletes:
        (def_del if needs_deferred(r, exe_name, allow_internal) else imm_del).append(r)

    for r in imm_del:
        try:
            t = os.path.join(base_dir, r)
            (shutil.rmtree(t, ignore_errors=True) if os.path.isdir(t) else os.remove(t))
        except:
            pass

    download_url_to_file(package_url, zip_path, user_agent, timeout=300, progress=progress, label=package_name)
    extract_needed_from_zip(zip_path, changed, stage_dir)

    imm_files, def_files = [], []
    for r in changed:
        (def_files if needs_deferred(r, exe_name, allow_internal) else imm_files).append(r)

    total = max(1, len(imm_files))
    for i, r in enumerate(imm_files, 1):
        if progress:
            progress(f"apply: {r}", int((i / total) * 100))
        atomic_copy_replace(os.path.join(stage_dir, r), os.path.join(base_dir, r))

    if def_files or def_del:
        if not getattr(sys, "frozen", False):
            raise RuntimeError("Deferred update requires frozen build")
        bat = build_deferred_bat(base_dir, stage_dir, def_files, def_del, exe_name, allow_internal)
        subprocess.Popen(["cmd", "/c", bat], creationflags=0x08000000)
        if settings:
            try:
                settings.setValue("last_release_tag", tag)
            except:
                pass
        return UpdateResult(True, True, touched, tag)

    if os.path.isdir(stage_dir):
        shutil.rmtree(stage_dir, ignore_errors=True)
    if settings:
        try:
            settings.setValue("last_release_tag", tag)
        except:
            pass
    return UpdateResult(True, False, touched, tag)
