from pathlib import Path

import pytest

from tender_enricher.config import Settings
from tender_enricher.db.migrate import upgrade_database
from tender_enricher.db.repository import SqlAlchemyResultRepository
from tender_enricher.db.session import make_engine
from tender_enricher.models import TenderInput

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        official_award_hosts=["awards.demo.test"],
        registry_hosts=["registry.demo.test"],
    )


@pytest.fixture
def tender():
    return TenderInput(
        tender_id="2026/123456", title="Hastane Yapımı", authority="Demo", location="Van"
    )


@pytest.fixture
def repository(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    upgrade_database(engine)
    yield SqlAlchemyResultRepository(engine)
    engine.dispose()


@pytest.fixture(autouse=True)
def no_live_network(monkeypatch):
    # Unit/integration checks must use fixtures and MockTransport, never the internet.
    import socket

    def blocked(*args, **kwargs):
        raise AssertionError("Live network is forbidden in the test suite")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
