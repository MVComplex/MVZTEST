from __future__ import annotations

import os
import json
import argparse
import hashlib
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def to_posix_rel(path: Path, base: Path) -> str:
    rel = path.relative_to(base)
    rel_posix = PurePosixPath(*rel.parts)
    return str(rel_posix)


def should_skip(rel_posix: str, include_internal: bool) -> bool:
    p = rel_posix.lower()

    if p == "manifest.json" or p.endswith("/manifest.json"):
        return True
    if p.endswith(".log") or p.endswith(".tmp"):
        return True
    if "/__pycache__/" in f"/{p}/":
        return True

    if not include_internal and p.startswith("_internal/"):
        return True

    return False


def iter_all_files(base_dir: Path, include_internal: bool):
    for p in base_dir.rglob("*"):
        if not p.is_file():
            continue
        rel = to_posix_rel(p, base_dir)
        if should_skip(rel, include_internal=include_internal):
            continue
        yield p, rel


def load_prev_manifest_map(prev_manifest_path: str) -> tuple[dict[str, str], set[str]]:
    if not prev_manifest_path:
        return {}, set()

    with open(prev_manifest_path, "r", encoding="utf-8", errors="replace") as f:
        m = json.load(f)

    mp: dict[str, str] = {}
    prev_paths: set[str] = set()

    for it in m.get("files", []) or []:
        if not isinstance(it, dict):
            continue
        rel = it.get("path")
        sha = it.get("sha256")
        if isinstance(rel, str) and isinstance(sha, str) and rel and sha:
            mp[rel] = sha.lower()
            prev_paths.add(rel)

    # if prev manifest had "delete" it's not needed here
    return mp, prev_paths


def build_maps(base_dir: Path, include_internal: bool) -> tuple[dict[str, dict], set[str]]:
    # returns: path -> {sha256,size,abs_path}, plus set(paths)
    mp: dict[str, dict] = {}
    paths: set[str] = set()

    for p, rel in iter_all_files(base_dir, include_internal=include_internal):
        sha = sha256_file(str(p)).lower()
        mp[rel] = {"sha256": sha, "size": p.stat().st_size, "abs": p}
        paths.add(rel)

    return mp, paths


def write_zip(files_to_pack: list[tuple[Path, str]], out_zip: Path):
    if out_zip.exists():
        out_zip.unlink()

    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for abs_path, rel in files_to_pack:
            z.write(abs_path, arcname=rel)


def write_manifest(
    out_manifest: Path,
    version: str,
    zip_name: str,
    include_internal: bool,
    files: list[dict],
    delete_list: list[str],
    delta: bool,
):
    files.sort(key=lambda x: x["path"])
    delete_list = sorted(delete_list)

    manifest = {
        "version": version,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "package": zip_name,
        "include_internal": include_internal,
        "delta": delta,
        "files": files,
        "delete": delete_list,
    }

    out_manifest.parent.mkdir(parents=True, exist_ok=True)
    with open(out_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Path to onedir folder, e.g. dist/MVZ")
    ap.add_argument("--out", default="release_out", help="Output folder")
    ap.add_argument("--version", required=True, help="Release version tag, e.g. v1.3.1")
    ap.add_argument("--include-internal", action="store_true", help="Include _internal in update.zip/manifest")
    ap.add_argument("--zip-name", default="update.zip")
    ap.add_argument("--manifest-name", default="manifest.json")
    ap.add_argument("--prev-manifest", default="", help="Path to previous manifest.json (optional)")
    args = ap.parse_args()

    base_dir = Path(args.input).resolve()
    out_dir = Path(args.out).resolve()
    zip_path = out_dir / args.zip_name
    manifest_path = out_dir / args.manifest_name

    prev_map, prev_paths = load_prev_manifest_map(args.prev_manifest)

    new_map, new_paths = build_maps(base_dir, include_internal=args.include_internal)

    delta_mode = bool(args.prev_manifest)

    # changed/new files
    changed: list[str] = []
    for rel, info in new_map.items():
        sha = info["sha256"]
        if prev_map.get(rel) != sha:
            changed.append(rel)

    # deleted files (were in prev, not in new)
    deleted = sorted(list(prev_paths - new_paths)) if delta_mode else []

    # what to pack into zip
    if delta_mode:
        to_pack = [(new_map[rel]["abs"], rel) for rel in sorted(changed)]
        files_list = [{"path": rel, "sha256": new_map[rel]["sha256"], "size": new_map[rel]["size"]} for rel in sorted(changed)]
    else:
        to_pack = [(new_map[rel]["abs"], rel) for rel in sorted(new_map.keys())]
        files_list = [{"path": rel, "sha256": new_map[rel]["sha256"], "size": new_map[rel]["size"]} for rel in sorted(new_map.keys())]

    write_zip(to_pack, zip_path)
    write_manifest(
        out_manifest=manifest_path,
        version=args.version,
        zip_name=args.zip_name,
        include_internal=args.include_internal,
        files=files_list,
        delete_list=deleted,
        delta=delta_mode,
    )

    print(str(zip_path))
    print(str(manifest_path))


if __name__ == "__main__":
    main()
