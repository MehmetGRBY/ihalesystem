"""Stoppable schedules for scanning, bounded web research and verified backups."""

import json
import logging
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import bulucu
import ekap_bulletin

from system_backup import create_snapshot
from system_bridge import EnrichmentService


class Operations:
    def __init__(self, service: EnrichmentService, runtime: Path, *, enabled: bool) -> None:
        self.service, self.runtime = service, runtime
        self.enabled = enabled and not service.demo
        self.stop = threading.Event()
        self.threads: list[threading.Thread] = []
        self.active: dict[str, threading.Thread] = {}

    def start(self) -> None:
        if self.enabled:
            thread = threading.Thread(target=self._loop, daemon=True, name="duzenli-islemler")
            self.threads.append(thread)
            thread.start()

    def close(self) -> None:
        self.stop.set()
        for thread in [*self.threads, *self.active.values()]:
            thread.join(timeout=5)

    def _loop(self) -> None:
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception:
                logging.getLogger(__name__).exception("Scheduled operation could not start")
            self.stop.wait(30)

    def _launch(self, name: str, target: Any) -> None:
        if name in self.active and self.active[name].is_alive():
            return
        thread = threading.Thread(target=target, daemon=True, name=name)
        self.active[name] = thread
        thread.start()

    def tick(self, now: datetime | None = None) -> None:
        if not self.enabled or self.stop.is_set():
            return
        now = now or datetime.now(UTC)
        for name, target in (("backup", self.backup), ("scan", self.scan)):
            state = self.service.state.get(name)
            if not state.get("next_at") or datetime.fromisoformat(state["next_at"]) <= now:
                self._launch(name, target)
        research = self.service.state.get("research")
        if not research.get("next_at") or datetime.fromisoformat(research["next_at"]) <= now:
            queued = self.service.request_web_batch(bulucu.records())
            self.service.state.put(
                "research",
                {
                    "last_at": now.isoformat(),
                    "queued": queued,
                    "next_at": (
                        now + timedelta(minutes=self.service.settings.research_interval_minutes)
                    ).isoformat(),
                },
            )

    def scan(self) -> None:
        state = self.service.state.get("scan")
        now = datetime.now(UTC)
        full = not state.get("next_full_at") or datetime.fromisoformat(state["next_full_at"]) <= now
        try:
            config = json.loads((bulucu.ROOT / "config.json").read_text(encoding="utf-8"))
            result = bulucu.scan() if full else bulucu.scan(only_sources={"ekap"})
            if result.get("busy"):
                state["next_at"] = (now + timedelta(minutes=1)).isoformat()
                self.service.state.put("scan", state)
                return
            finished = datetime.now(UTC)
            next_full = (
                finished + timedelta(minutes=config.get("interval_minutes", 360))
                if full
                else datetime.fromisoformat(state["next_full_at"])
            )
            source = next(
                (
                    s
                    for s in config["sources"]
                    if s.get("adapter") == "ekap_bulletin" and s.get("enabled", True)
                ),
                None,
            )
            pending = ekap_bulletin.progress_summary(source)["remaining_days"] if source else 0
            next_at = (
                min(
                    next_full,
                    finished + timedelta(minutes=config.get("archive_interval_minutes", 1)),
                )
                if pending
                else next_full
            )
            errors = sum(item.get("status") == "error" for item in result.get("sources", []))
            succeeded = any(
                item.get("status") in {"ok", "partial"} for item in result.get("sources", [])
            )
            if not succeeded:
                next_at = min(next_at, finished + timedelta(minutes=5))
            self.service.state.put(
                "scan",
                {
                    "last_at": finished.isoformat(),
                    "next_at": next_at.isoformat(),
                    "next_full_at": next_full.isoformat(),
                    "source_errors": errors,
                    "status": "error" if not succeeded else "partial" if errors else "ok",
                },
            )
        except Exception:
            self.service.state.put(
                "scan",
                {
                    **state,
                    "status": "error",
                    "last_error_at": now.isoformat(),
                    "next_at": (now + timedelta(minutes=5)).isoformat(),
                },
            )

    def backup(self) -> None:
        now = datetime.now(UTC)
        old = self.service.state.get("backup")
        try:
            database = self.service.engine.url.database
            if (
                self.service.engine.url.get_backend_name() != "sqlite"
                or not database
                or Path(database).resolve() != self.runtime / "enrichment.sqlite3"
            ):
                raise ValueError("Automatic snapshots require the runtime SQLite database")
            # Freeze application writers so both DBs and the PDF set describe one state.
            with bulucu.SCAN_LOCK, self.service.processing_lock, self.service._lock:
                snapshot = create_snapshot(
                    self.runtime,
                    self.runtime.parent.parent / "backups" / self.runtime.name,
                    keep=self.service.settings.backup_keep,
                )
            finished = datetime.now(UTC)
            self.service.state.put(
                "backup",
                {
                    "status": "ok",
                    "last_success_at": finished.isoformat(),
                    "snapshot": snapshot.name,
                    "next_at": (
                        finished + timedelta(hours=self.service.settings.backup_interval_hours)
                    ).isoformat(),
                },
            )
        except Exception:
            self.service.state.put(
                "backup",
                {
                    **old,
                    "status": "error",
                    "last_error_at": now.isoformat(),
                    "next_at": (now + timedelta(minutes=30)).isoformat(),
                },
            )

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "scan": self.service.state.get("scan"),
            "research": self.service.state.get("research"),
            "backup": self.service.state.get("backup"),
            "backup_running": bool(self.active.get("backup") and self.active["backup"].is_alive()),
            "research_batch_size": self.service.settings.research_batch_size,
            "research_interval_minutes": self.service.settings.research_interval_minutes,
        }
