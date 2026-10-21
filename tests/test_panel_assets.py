from pathlib import Path

import bulucu
import pytest


def response(path):
    handler = object.__new__(bulucu.Handler)
    handler.path = path
    output = []
    handler.send = lambda data, code=200, **kwargs: output.append((data, code, kwargs))
    handler.do_GET()
    return output[0]


@pytest.mark.parametrize(
    "path,kind",
    [
        ("/panel.css", "text/css; charset=utf-8"),
        ("/panel-data.js", "text/javascript; charset=utf-8"),
        ("/assets/search.svg", "image/svg+xml"),
        ("/assets/InterVariable.woff2", "font/woff2"),
    ],
)
def test_local_ui_assets_are_available_with_correct_types(path, kind):
    data, code, headers = response(path)
    assert code == 200 and data
    assert headers["content_type"] == kind


@pytest.mark.parametrize(
    "path",
    [
        "/assets/../config.json",
        "/assets/%2e%2e/.env",
        "/assets/.env",
        "/assets/none.svg",
        "/assets/inter-LICENSE.txt",
        "/assets/sub/search.svg",
    ],
)
def test_asset_route_does_not_expose_configuration_or_arbitrary_files(path):
    _, code, _ = response(path)
    assert code == 404


def test_asset_route_rejects_symlinks(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    assets.mkdir()
    outside = tmp_path / "outside.svg"
    outside.write_text("private", encoding="utf-8")
    try:
        (assets / "search.svg").symlink_to(outside)
    except OSError:
        pytest.skip("Symlinks are unavailable in this environment")
    monkeypatch.setattr(bulucu, "ROOT", Path(tmp_path))
    _, code, _ = response("/assets/search.svg")
    assert code == 404
