from __future__ import annotations

import os
import sys
import json
import time
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

ProgressCb = Callable[[str, int], None]  # (label, percent)


@dataclass
class UpdateResult:
    updated_any: bool
    restarted: bool
    changed_files: list[str]
    new_version: str


def app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _safe_rel_path(rel: str) -> str:
    rel = (rel or "").replace("\\", "/").lstrip("/")
    p = PurePosixPath(rel)

    if p.is_absolute():
        raise ValueError(f"Bad path (absolute): {rel}")
    if ".." in p.parts:
        raise ValueError(f"Bad path (traversal): {rel}")
    if len(p.parts) > 0 and ":" in p.parts[0]:
        raise ValueError(f"Bad path (drive): {rel}")

    return str(p)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def atomic_copy_replace(src: str, dst: str):
    dst_dir = os.path.dirname(dst)
    if dst_dir:
        os.makedirs(dst_dir, exist_ok=True)

    tmp = dst + ".tmp"
    try:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def http_get_json(url: str, user_agent: str, timeout: int = 10) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def find_asset_url(release: dict, asset_name: str) -> Optional[str]:
    for a in release.get("assets", []) or []:
        if a.get("name") == asset_name:
            return a.get("browser_download_url")
    return None


def download_url_to_file(url: str, dst_path: str, user_agent: str, timeout: int = 60,
                         progress: Optional[ProgressCb] = None, label: str = ""):
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        total = int(response.headers.get("Content-Length", 0) or 0)
        downloaded = 0

        if progress:
            progress(label, 0)

        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
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

    return m


def compute_changed_files(manifest: dict, base_dir: str) -> list[str]:
    changed: list[str] = []

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
            local_sha = sha256_file(local).lower()
        except Exception:
            changed.append(rel)
            continue

        if local_sha != sha:
            changed.append(rel)

    return changed


def extract_needed_from_zip(zip_path: str, needed_paths: list[str], out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    needed_paths = [_safe_rel_path(p) for p in needed_paths]

    with zipfile.ZipFile(zip_path, "r") as z:
        names = set(z.namelist())

        for rel in needed_paths:
            if rel not in names:
                raise RuntimeError(f"update.zip missing file: {rel}")

            out_path = os.path.join(out_dir, rel)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)

            with z.open(rel, "r") as src, open(out_path, "wb") as dst:
                shutil.copyfileobj(src, dst)


def needs_deferred(rel: str, exe_name: str, allow_internal: bool) -> bool:
    p = rel.replace("\\", "/").lower()
    if p == exe_name.lower():
        return True
    if allow_internal and p.startswith("_internal/"):
        return True
    return False


def has_bin_changes(paths: list[str]) -> bool:
    for p in paths:
        if p.replace("\\", "/").lower().startswith("bin/"):
            return True
    return False


def build_deferred_bat(app_dir_path: str, stage_dir: str, deferred: list[str], exe_name: str,
                       allow_internal: bool) -> str:
    tmp_dir = tempfile.gettempdir()
    bat_path = os.path.join(tmp_dir, "MVZ_update_files.bat")

    exe_basename = os.path.basename(exe_name)

    has_internal = allow_internal and any(p.replace("\\", "/").lower().startswith("_internal/") for p in deferred)
    has_exe = any(p.replace("\\", "/").lower() == exe_name.lower() for p in deferred)

    lines: list[str] = []
    lines.append("@echo off")
    lines.append("chcp 65001 >nul")
    lines.append("setlocal")
    lines.append(f"set APPDIR={app_dir_path}")
    lines.append(f"set STAGE={stage_dir}")
    lines.append("")
    lines.append(":wait_loop")
    lines.append(f'tasklist /FI "IMAGENAME eq {exe_basename}" 2>NUL | find /I "{exe_basename}" >NUL')
    lines.append("if not errorlevel 1 (")
    lines.append("  timeout /t 1 /nobreak >nul")
    lines.append("  goto wait_loop")
    lines.append(")")
    lines.append("")

    if has_internal:
        lines.append('if exist "%STAGE%\\_internal" (')
        lines.append('  robocopy "%STAGE%\\_internal" "%APPDIR%\\_internal" /E /NFL /NDL /NJH /NJS /NP >nul')
        lines.append(")")

    if has_exe:
        lines.append(f'if exist "%STAGE%\\{exe_basename}" (')
        lines.append(f'  copy /y "%STAGE%\\{exe_basename}" "%APPDIR%\\{exe_basename}" >nul')
        lines.append(")")

    for rel in deferred:
        rel_norm = rel.replace("\\", "/")
        low = rel_norm.lower()
        if low == exe_name.lower():
            continue
        if allow_internal and low.startswith("_internal/"):
            continue

        win_rel = rel_norm.replace("/", "\\")
        dst_dir = os.path.dirname(win_rel)
        if dst_dir:
            lines.append(f'mkdir "%APPDIR%\\{dst_dir}" >nul 2>nul')
        lines.append(f'copy /y "%STAGE%\\{win_rel}" "%APPDIR%\\{win_rel}" >nul')

    lines.append("")
    lines.append(f'start "" "%APPDIR%\\{exe_basename}"')
    lines.append('rmdir /s /q "%STAGE%" >nul 2>nul')
    lines.append('del "%~f0" >nul 2>nul')
    lines.append("endlocal")

    with open(bat_path, "w", encoding="utf-8", errors="ignore") as f:
        f.write("\r\n".join(lines))

    return bat_path


def apply_update_from_release(
    owner: str,
    repo: str,
    current_version: str,
    manifest_name: str = "manifest.json",
    package_name: str = "update.zip",
    user_agent: str = "MVZ-Updater",
    allow_internal: bool = False,
    progress: Optional[ProgressCb] = None,
    stop_bin_cb: Optional[Callable[[], None]] = None,
    settings: Optional[Any] = None,
) -> UpdateResult:
    base_dir = app_dir()

    latest = http_get_json(f"https://api.github.com/repos/{owner}/{repo}/releases/latest", user_agent=user_agent)
    tag = (latest.get("tag_name") or "").strip()
    if not tag:
        return UpdateResult(False, False, [], "")

    def version_tuple(v: str) -> tuple[int, int, int]:
        v = (v or "").strip().split()[0].lstrip("v")
        parts = v.split(".")
        out: list[int] = []
        for p in parts:
            try:
                out.append(int(p))
            except Exception:
                out.append(0)
        while len(out) < 3:
            out.append(0)
        return tuple(out[:3])  # type: ignore

    if version_tuple(tag) <= version_tuple(current_version):
        return UpdateResult(False, False, [], tag)

    manifest_url = find_asset_url(latest, manifest_name)
    package_url = find_asset_url(latest, package_name)
    if not manifest_url or not package_url:
        return UpdateResult(False, False, [], tag)

    exe_name = os.path.basename(sys.executable) if getattr(sys, "frozen", False) else "MVZ.exe"

    tmp_dir = tempfile.gettempdir()
    manifest_path = os.path.join(tmp_dir, "mvz_manifest.json")
    zip_path = os.path.join(tmp_dir, "mvz_update.zip")
    stage_dir = os.path.join(tmp_dir, "mvz_update_stage")

    try:
        if os.path.isdir(stage_dir):
            shutil.rmtree(stage_dir, ignore_errors=True)
    except Exception:
        pass

    download_url_to_file(manifest_url, manifest_path, user_agent=user_agent, progress=progress, label="manifest.json")
    manifest = load_manifest(manifest_path)

    changed = compute_changed_files(manifest, base_dir)
    if not changed:
        if settings is not None:
            try:
                settings.setValue("last_release_tag", tag)
            except Exception:
                pass
        return UpdateResult(False, False, [], tag)

    if has_bin_changes(changed) and stop_bin_cb is not None:
        stop_bin_cb()
        time.sleep(1)

    download_url_to_file(package_url, zip_path, user_agent=user_agent, progress=progress, label="update.zip")
    extract_needed_from_zip(zip_path, changed, stage_dir)

    immediate: list[str] = []
    deferred: list[str] = []

    for rel in changed:
        if needs_deferred(rel, exe_name=exe_name, allow_internal=allow_internal):
            deferred.append(rel)
        else:
            immediate.append(rel)

    # apply immediate
    total = max(1, len(immediate))
    for i, rel in enumerate(immediate, start=1):
        if progress:
            progress(f"apply: {rel}", int((i / total) * 100))

        src = os.path.join(stage_dir, rel)
        dst = os.path.join(base_dir, rel)
        if not os.path.isfile(src):
            raise RuntimeError(f"Stage missing: {rel}")
        atomic_copy_replace(src, dst)

    # deferred: restart required
    if deferred:
        if not getattr(sys, "frozen", False):
            raise RuntimeError("Deferred update requires frozen build")

        bat = build_deferred_bat(
            app_dir_path=base_dir,
            stage_dir=stage_dir,
            deferred=deferred,
            exe_name=exe_name,
            allow_internal=allow_internal,
        )

        subprocess.Popen(["cmd", "/c", bat], creationflags=0x08000000)

        if settings is not None:
            try:
                settings.setValue("last_release_tag", tag)
            except Exception:
                pass

        return UpdateResult(True, True, changed, tag)

    if settings is not None:
        try:
            settings.setValue("last_release_tag", tag)
        except Exception:
            pass

    return UpdateResult(True, False, changed, tag)
