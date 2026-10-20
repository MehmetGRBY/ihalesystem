import json
from datetime import UTC, datetime, timedelta

import bulucu
import ekap_bulletin
import pytest
from test_system_integration import seeded
from test_system_integration import service as service

from system_bridge import ResearchRequest
from system_operations import Operations
from system_state import StateStore


def live_rows(service, count=4):
    base = seeded()[0]
    service.demo = False
    service.settings = service.settings.model_copy(
        update={
            "searxng_url": "http://127.0.0.1:8080",
            "research_batch_size": 2,
            "research_daily_limit": 3,
        }
    )
    today = datetime.now(bulucu.TR)
    rows = [
        dict(
            base,
            id=f"{n:024x}",
            is_demo=False,
            research_links={},
            published_date_raw=(today - timedelta(days=n)).strftime("%d.%m.%Y"),
            contractors=[{"name": f"Firma {n} Limited Şirketi"}],
            opportunity={"status": "yuklenici", "priority": 85},
        )
        for n in range(count)
    ]
    with bulucu.connect() as conn:
        bulucu.save_items(conn, rows)
    return rows


def test_bounded_batches_daily_budget_and_restart(service):
    rows = live_rows(service)
    assert service.request_web_batch(rows[::-1]) == 2
    assert service.job(rows[0]["id"])["state"] == "queued"
    assert service.job(rows[1]["id"])["state"] == "queued"
    assert service.request_web_batch(rows) == 1
    assert service.request_web_batch(rows) == 0
    assert service.status()["automatic_daily_used"] == 3
    # Reconstructing operational state does not reset the quota.
    assert StateStore(bulucu.DB).get("search_health") == {}
    service.state = StateStore(bulucu.DB)
    assert service.request_web_batch(rows) == 0
    assert service._queue.qsize() == 3


def test_archived_old_unknown_date_and_complete_contacts_skipped(service):
    rows = live_rows(service)
    rows[0]["opportunity"]["status"] = "arsiv"
    rows[1]["published_date_raw"] = "01.01.2020"
    rows[2]["published_date_raw"] = ""
    row = rows[3]
    service.request(row, ResearchRequest(id=row["id"]))
    with bulucu.connect() as conn:
        conn.execute(
            "UPDATE enrichment_jobs SET state=?,payload=? WHERE id=?",
            (
                "completed",
                json.dumps({"winner": {"phone": "+902120000000", "email": "a@b.test"}}),
                row["id"],
            ),
        )
    assert service.request_web_batch(rows) == 0


def test_local_result_upgraded_preserving_manual_links_and_payload(service):
    row = live_rows(service, 1)[0]
    request = ResearchRequest(id=row["id"], company_urls=["https://atlas.example/contact"])
    service.request(row, request, local_only=True)
    payload = {"status": "partial", "winner": None}
    with bulucu.connect() as conn:
        conn.execute(
            "UPDATE enrichment_jobs SET state=?,payload=? WHERE id=?",
            ("completed", json.dumps(payload), row["id"]),
        )
    assert service.request_web_batch([row]) == 1
    job = service.job(row["id"])
    assert job["local_only"] == 0
    assert json.loads(job["options"])["company_urls"] == ["https://atlas.example/contact"]
    assert json.loads(job["payload"]) == payload
    with bulucu.connect() as conn:
        conn.execute(
            "UPDATE enrichment_jobs SET state='completed',finished_at=?",
            (datetime.now(UTC).isoformat(),),
        )
    assert service.request_web_batch([row]) == 0


def test_health_failure_and_recovery_persist_without_queries(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.search_observation("searxng:brave", "ok", 4)
    store.search_observation("searxng:brave", "error", 0)
    failed = store.get("search_health")["searxng:brave"]
    assert failed["last_success_at"] and failed["last_error_at"]
    store.search_observation("searxng:brave", "empty", 0)
    recovered = StateStore(store.database).get("search_health")["searxng:brave"]
    assert recovered["status"] == "empty"
    assert recovered["last_error_at"] == failed["last_error_at"]
    assert not {"query", "url", "key"} & recovered.keys()


def test_disabled_and_demo_schedules_do_no_work(service, monkeypatch):
    operations = Operations(service, bulucu.DATA.parent, enabled=True)
    monkeypatch.setattr(operations, "_launch", lambda *args: pytest.fail("demo automation"))
    operations.tick()
    assert operations.status()["enabled"] is False
    service.demo = False
    operations = Operations(service, bulucu.DATA.parent, enabled=False)
    operations.tick()
    assert service.jobs() == {}


def test_scheduler_respects_persisted_due_times_and_stop(service, monkeypatch):
    service.demo = False
    ops = Operations(service, bulucu.DATA.parent, enabled=True)
    now = datetime.now(UTC)
    for name in ("backup", "scan"):
        service.state.put(name, {"next_at": (now + timedelta(hours=1)).isoformat()})
    launched = []
    monkeypatch.setattr(ops, "_launch", lambda name, target: launched.append(name))
    monkeypatch.setattr(service, "request_web_batch", lambda rows: 2)
    ops.tick(now)
    assert launched == []
    assert service.state.get("research")["queued"] == 2
    ops.tick(now)
    assert service.state.get("research")["last_at"] == now.isoformat()
    ops.tick(now + timedelta(hours=2))
    assert launched == ["backup", "scan"]
    ops.close()
    ops.tick(now + timedelta(days=1))
    assert launched == ["backup", "scan"]


def test_scan_backfill_and_error_are_rescheduled(service, monkeypatch):
    service.demo = False
    ops = Operations(service, bulucu.DATA.parent, enabled=True)
    calls = []
    monkeypatch.setattr(
        bulucu, "scan", lambda **kwargs: calls.append(kwargs) or {"sources": [{"status": "ok"}]}
    )
    monkeypatch.setattr(ekap_bulletin, "progress_summary", lambda source: {"remaining_days": 3})
    ops.scan()
    state = service.state.get("scan")
    assert state["status"] == "ok"
    assert datetime.fromisoformat(state["next_at"]) < datetime.fromisoformat(state["next_full_at"])
    ops.scan()
    assert calls == [{}, {"only_sources": {"ekap"}}]

    def failing(**kwargs):
        raise OSError("upstream down")

    monkeypatch.setattr(bulucu, "scan", failing)
    ops.scan()
    assert service.state.get("scan")["status"] == "error"
    assert service.state.get("scan")["next_at"]


def test_scheduled_backup_success_and_failure_preserves_last_good(service, monkeypatch):
    import system_operations

    old_path = bulucu.DB
    new_path = old_path.parent / "ihaleler.sqlite3"
    old_path.rename(new_path)
    monkeypatch.setattr(bulucu, "DB", new_path)
    service.state = StateStore(new_path)
    service.demo = False
    ops = Operations(service, bulucu.DATA.parent, enabled=True)
    ops.backup()
    first = ops.status()["backup"]
    assert first["status"] == "ok"
    assert first["snapshot"].startswith("snapshot-")

    def failure(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(system_operations, "create_snapshot", failure)
    ops.backup()
    failed = ops.status()["backup"]
    assert failed["status"] == "error"
    assert failed["last_success_at"] == first["last_success_at"]
    assert failed["snapshot"] == first["snapshot"]
    assert datetime.fromisoformat(failed["next_at"]) < datetime.fromisoformat(first["next_at"])


def test_overlapping_background_operation_is_not_launched_twice(service):
    import threading

    service.demo = False
    ops = Operations(service, bulucu.DATA.parent, enabled=True)
    entered, release = threading.Event(), threading.Event()
    calls = []

    def backup():
        calls.append(1)
        entered.set()
        release.wait(2)

    ops._launch("backup", backup)
    assert entered.wait(2)
    try:
        ops._launch("backup", backup)
        assert calls == [1]
    finally:
        release.set()
        ops.close()
