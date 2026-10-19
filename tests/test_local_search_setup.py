import json

import pytest
from dotenv import dotenv_values

from scripts import local_search
from tender_enricher.config import Settings


def test_local_setup_preserves_api_keys_and_adds_search_to_selected_providers(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(local_search, "ROOT", tmp_path)
    env = tmp_path / ".env"
    env.write_text('TE_SERPER_API_KEY="secret-keep-this"\nTE_SEARCH_PROVIDERS=["serper"]\n')
    local_search.configure_app(Settings(_env_file=env))
    values = dotenv_values(env)
    assert values["TE_SERPER_API_KEY"] == "secret-keep-this"
    assert values["TE_SEARXNG_URL"] == local_search.LOCAL_URL
    assert json.loads(values["TE_SEARCH_PROVIDERS"]) == ["serper", "searxng"]
    assert json.loads(values["TE_SEARXNG_ENGINES"]) == local_search.ENGINES


def test_ensure_does_not_start_docker_without_local_search_selected(tmp_path, monkeypatch):
    monkeypatch.setattr(local_search, "ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["local_search.py", "ensure"])
    monkeypatch.setattr(local_search, "ensure_docker", lambda: pytest.fail("Docker started"))
    assert local_search.main() == 0


def test_start_preserves_external_searxng_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(local_search, "ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["local_search.py", "start"])
    env = tmp_path / ".env"
    original = "TE_SEARXNG_URL=https://search.example/\nTE_TAVILY_API_KEY=secret\n"
    env.write_text(original)
    monkeypatch.setattr(local_search, "ensure_docker", lambda: pytest.fail("Docker started"))
    assert local_search.main() == 2
    assert env.read_text() == original


def test_failed_start_does_not_point_app_at_unavailable_service(tmp_path, monkeypatch):
    monkeypatch.setattr(local_search, "ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["local_search.py", "start"])
    monkeypatch.setattr(local_search, "ensure_docker", lambda: None)
    monkeypatch.setattr(local_search, "prepare_config", lambda: None)
    monkeypatch.setattr(local_search, "compose", lambda *args: None)

    def fail():
        raise RuntimeError("Service unavailable")

    monkeypatch.setattr(local_search, "verify_service", fail)
    assert local_search.main() == 2
    assert not (tmp_path / ".env").exists()


def test_configured_engines_are_not_reported_as_service_health(monkeypatch):
    monkeypatch.setattr(
        local_search,
        "request_json",
        lambda _: {
            "instance_name": local_search.INSTANCE,
            "engines": [{"name": "brave", "enabled": True}],
        },
    )
    with pytest.raises(RuntimeError):
        local_search.verify_service()
