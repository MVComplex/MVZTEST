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


def iter_files(base_dir: Path, include_internal: bool):
    for p in base_dir.rglob("*"):
        if not p.is_file():
            continue
        rel = to_posix_rel(p, base_dir)
        if should_skip(rel, include_internal=include_internal):
            continue
        yield p, rel


def build_update_zip(base_dir: Path, out_zip: Path, include_internal: bool):
    if out_zip.exists():
        out_zip.unlink()

    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p, rel in iter_files(base_dir, include_internal=include_internal):
            z.write(p, arcname=rel)


def build_manifest(base_dir: Path, out_manifest: Path, version: str, zip_name: str, include_internal: bool):
    files = []
    for p, rel in iter_files(base_dir, include_internal=include_internal):
        files.append({
            "path": rel,
            "sha256": sha256_file(str(p)),
            "size": p.stat().st_size,
        })

    files.sort(key=lambda x: x["path"])

    manifest = {
        "version": version,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "package": zip_name,
        "include_internal": include_internal,
        "files": files,
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
    args = ap.parse_args()

    base_dir = Path(args.input).resolve()
    out_dir = Path(args.out).resolve()
    zip_path = out_dir / args.zip_name
    manifest_path = out_dir / args.manifest_name

    build_update_zip(base_dir, zip_path, include_internal=args.include_internal)
    build_manifest(base_dir, manifest_path, version=args.version, zip_name=args.zip_name, include_internal=args.include_internal)

    print(str(zip_path))
    print(str(manifest_path))


if __name__ == "__main__":
    main()
