import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from system_backup import create_snapshot, restore_snapshot, verify


@pytest.fixture
def runtime(tmp_path):
    root = tmp_path / "live"
    (root / "discovery/ekap-bulten").mkdir(parents=True)
    for path in (root / "discovery/ihaleler.sqlite3", root / "enrichment.sqlite3"):
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, name TEXT)")
            connection.execute("INSERT INTO records VALUES (1,'ihale')")
    (root / "discovery/ekap-bulten/BULTEN_20102026_YAPIM.pdf").write_bytes(b"%PDF-test")
    (root / ".env").write_text("SECRET=not-in-backup")
    return root


def test_live_database_backup_verified_restore_and_retention(runtime, tmp_path):
    destination = tmp_path / "backups"
    first = create_snapshot(runtime, destination, keep=2)
    second = create_snapshot(runtime, destination, keep=2)
    pdf = Path("discovery/ekap-bulten/BULTEN_20102026_YAPIM.pdf")
    assert (first / pdf).stat().st_ino == (second / pdf).stat().st_ino
    assert (runtime / pdf).stat().st_ino != (first / pdf).stat().st_ino
    third = create_snapshot(runtime, destination, keep=2)
    assert not first.exists() and second.exists() and third.exists()
    assert len(verify(third)["files"]) == 3
    assert not (third / ".env").exists()
    restored = restore_snapshot(third, tmp_path / "restored")
    with closing(sqlite3.connect(restored / "discovery/ihaleler.sqlite3")) as connection:
        assert connection.execute("SELECT name FROM records").fetchone() == ("ihale",)
    assert (restored / pdf).read_bytes() == b"%PDF-test"
    with pytest.raises(ValueError, match="yeni bir hedef"):
        restore_snapshot(third, restored)


def test_corrupt_backup_rejected_and_new_snapshot_can_recover(runtime, tmp_path):
    first = create_snapshot(runtime, tmp_path / "backups")
    (first / "enrichment.sqlite3").write_bytes(b"broken")
    with pytest.raises(ValueError, match="bütünlük"):
        restore_snapshot(first, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()
    second = create_snapshot(runtime, tmp_path / "backups")
    assert verify(second)


def test_malicious_manifest_and_symlinks_rejected(runtime, tmp_path):
    snapshot = create_snapshot(runtime, tmp_path / "backups")
    manifest = json.loads((snapshot / "manifest.json").read_text())
    manifest["files"]["../../escape"] = {"sha256": "fake", "size": 1}
    (snapshot / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        verify(snapshot)
    with pytest.raises(ValueError):
        create_snapshot(runtime, runtime / "backups")


def test_failed_snapshot_keeps_previous_and_cleans_partial(runtime, tmp_path, monkeypatch):
    import system_backup

    destination = tmp_path / "backups"
    previous = create_snapshot(runtime, destination)
    original = system_backup.digest

    def failure(path):
        if ".pending-" in str(path):
            raise OSError("disk full")
        return original(path)

    monkeypatch.setattr(system_backup, "digest", failure)
    with pytest.raises(OSError):
        create_snapshot(runtime, destination)
    assert previous.exists()
    assert not list(destination.glob(".pending-*"))
