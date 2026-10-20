"""Verified local SQLite/PDF snapshots and restore into a new, empty directory."""

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from filelock import FileLock

SNAPSHOT = re.compile(r"^snapshot-\d{8}T\d{12}Z$")


def digest(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def valid_member(name: str) -> bool:
    return name in {"discovery/ihaleler.sqlite3", "enrichment.sqlite3"} or bool(
        re.fullmatch(r"discovery/ekap-bulten/BULTEN_\d{8}_[A-Z_]+\.pdf", name)
    )


def verify(snapshot: Path) -> dict[str, Any]:
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    files = manifest.get("files")
    if manifest.get("version") != 1 or not isinstance(files, dict) or not files:
        raise ValueError("Geçersiz yedek manifestosu.")
    if not {"discovery/ihaleler.sqlite3", "enrichment.sqlite3"}.issubset(files):
        raise ValueError("Yedekte iki veritabanı da bulunmalı.")
    for name, info in files.items():
        path = snapshot / name
        if (
            not valid_member(name)
            or not isinstance(info, dict)
            or path.is_symlink()
            or not path.is_file()
            or not path.resolve().is_relative_to(snapshot.resolve())
            or path.stat().st_size != info.get("size")
            or digest(path) != info.get("sha256")
        ):
            raise ValueError("Yedek bütünlük kontrolü başarısız.")
        if name.endswith(".sqlite3"):
            with closing(
                sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
            ) as connection:
                if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise ValueError("Yedek veritabanı bütünlük kontrolü başarısız.")
                if connection.execute("PRAGMA foreign_key_check").fetchall():
                    raise ValueError("Yedek veritabanı ilişkileri geçersiz.")
    return manifest


def create_snapshot(runtime: Path, destination: Path, *, keep: int = 7) -> Path:
    runtime, destination = runtime.resolve(), destination.resolve()
    if destination == runtime or destination.is_relative_to(runtime):
        raise ValueError("Yedek klasörü çalışma verilerinin dışında olmalı.")
    if keep < 2:
        raise ValueError("En az iki yedek saklanmalı.")
    destination.mkdir(parents=True, exist_ok=True)
    with FileLock(destination / ".backup.lock", timeout=0):
        snapshots = sorted(
            p for p in destination.iterdir() if p.is_dir() and SNAPSHOT.fullmatch(p.name)
        )
        previous = None
        old_files = {}
        # Reuse only immutable files from a verified snapshot, never hard-link live PDFs.
        for candidate in reversed(snapshots):
            try:
                old_files = verify(candidate)["files"]
                previous = candidate
                break
            except (ValueError, OSError):
                continue
        staging = Path(tempfile.mkdtemp(prefix=".pending-", dir=destination))
        try:
            files: dict[str, Any] = {}
            for name in ("discovery/ihaleler.sqlite3", "enrichment.sqlite3"):
                source, target = runtime / name, staging / name
                if source.is_symlink() or not source.is_file():
                    raise ValueError("Yerel SQLite veritabanı bulunamadı.")
                target.parent.mkdir(parents=True, exist_ok=True)
                with closing(
                    sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
                ) as original:
                    with closing(sqlite3.connect(target)) as backup:
                        original.backup(backup, pages=256)
                files[name] = {"size": target.stat().st_size, "sha256": digest(target)}
            for source in sorted((runtime / "discovery/ekap-bulten").glob("BULTEN_*.pdf")):
                name = source.relative_to(runtime).as_posix()
                if source.is_symlink() or not valid_member(name):
                    continue
                target = staging / name
                target.parent.mkdir(parents=True, exist_ok=True)
                checksum = digest(source)
                info = {"size": source.stat().st_size, "sha256": checksum}
                if previous and old_files.get(name) == info:
                    try:
                        os.link(previous / name, target)
                    except OSError:
                        shutil.copy2(source, target)
                else:
                    shutil.copy2(source, target)
                files[name] = info
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            manifest = {"version": 1, "created_at": datetime.now(UTC).isoformat(), "files": files}
            (staging / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            verify(staging)
            final = destination / ("snapshot-" + stamp)
            staging.rename(final)
            # Retention happens only after a complete, verified replacement exists.
            for expired in [*snapshots, final][:-keep]:
                shutil.rmtree(expired)
            return final
        finally:
            if staging.exists():
                shutil.rmtree(staging)


def restore_snapshot(snapshot: Path, destination: Path) -> Path:
    snapshot, destination = snapshot.resolve(), destination.resolve()
    if destination.exists():
        raise ValueError("Geri yükleme için mevcut olmayan yeni bir hedef seçin.")
    if destination.is_relative_to(snapshot) or snapshot.is_relative_to(destination):
        raise ValueError("Geri yükleme hedefi yedekten ayrı olmalı.")
    with FileLock(snapshot.parent / ".backup.lock", timeout=0):
        manifest = verify(snapshot)
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".restore-", dir=destination.parent))
        try:
            for name in manifest["files"]:
                target = staging / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(snapshot / name, target)
                if digest(target) != manifest["files"][name]["sha256"]:
                    raise ValueError("Geri yüklenen dosya doğrulanamadı.")
            staging.rename(destination)
            return destination
        finally:
            if staging.exists():
                shutil.rmtree(staging)
