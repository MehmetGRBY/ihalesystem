import base64
import io
import json
import os
import plistlib
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import desktop_launcher as launcher
from scripts import install_desktop_shortcut as installer


@pytest.mark.parametrize(
    ("payload", "demo", "expected"),
    [
        ({"is_demo": False, "configured_sources": [], "enrichment": {"counts": {}}}, False, True),
        ({"is_demo": True, "configured_sources": [], "enrichment": {"counts": {}}}, False, False),
        ({"status": "ok"}, False, False),
        ([], False, False),
    ],
)
def test_probe_identifies_expected_app_without_using_a_proxy(monkeypatch, payload, demo, expected):
    response = io.BytesIO(json.dumps(payload).encode())
    opener = Mock()
    opener.open.return_value = response
    monkeypatch.setattr(launcher, "build_opener", lambda *args: opener)
    assert launcher.panel_ready("http://127.0.0.1:8765/", demo=demo) is expected
    opener.open.assert_called_once_with("http://127.0.0.1:8765/api/status", timeout=2)


def test_invalid_http_reply_is_not_treated_as_the_application(monkeypatch):
    opener = Mock()
    opener.open.return_value = io.BytesIO(b"<html>Another server</html>")
    monkeypatch.setattr(launcher, "build_opener", lambda *args: opener)
    assert not launcher.panel_ready("http://127.0.0.1:8765/")


def test_running_app_opens_immediately_without_starting_docker_or_another_server(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(launcher, "panel_ready", lambda *args, **kwargs: True)
    start, docker, browser = Mock(), Mock(), Mock()
    monkeypatch.setattr(launcher.subprocess, "Popen", start)
    monkeypatch.setattr(launcher.subprocess, "run", docker)
    monkeypatch.setattr(launcher.webbrowser, "open", browser)
    assert launcher.launch(tmp_path) == "http://127.0.0.1:8765/"
    assert not start.called and not docker.called
    browser.assert_called_once_with("http://127.0.0.1:8765/")


def test_stopped_app_starts_once_and_waits_before_opening_browser(tmp_path, monkeypatch):
    python = launcher.python_path(tmp_path)
    python.parent.mkdir(parents=True)
    python.touch()
    replies = iter([False, False, True])
    monkeypatch.setattr(launcher, "panel_ready", lambda *args, **kwargs: next(replies))
    process = Mock()
    process.poll.return_value = None
    start, docker, browser = Mock(return_value=process), Mock(), Mock()
    monkeypatch.setattr(launcher.subprocess, "Popen", start)
    monkeypatch.setattr(launcher.subprocess, "run", docker)
    monkeypatch.setattr(launcher.webbrowser, "open", browser)
    launcher.launch(tmp_path)
    start.assert_called_once()
    assert start.call_args.args[0] == [str(python), str(tmp_path / "app.py"), "--port", "8765"]
    assert start.call_args.kwargs["stdin"] == subprocess.DEVNULL
    assert start.call_args.kwargs["stdout"].name == str(
        tmp_path / "data/runtime/desktop-launcher.log"
    )
    assert docker.call_args.args[0][-1] == "ensure"
    browser.assert_called_once()


def test_two_simultaneous_clicks_recheck_after_acquiring_the_launch_lock(tmp_path, monkeypatch):
    replies = iter([False, True])
    monkeypatch.setattr(launcher, "panel_ready", lambda *args, **kwargs: next(replies))
    start = Mock()
    monkeypatch.setattr(launcher.subprocess, "Popen", start)
    launcher.launch(tmp_path, browser=False)
    assert not start.called


def test_failed_child_does_not_open_a_broken_panel(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "panel_ready", lambda *args, **kwargs: False)
    process = Mock()
    process.poll.return_value = 2
    with pytest.raises(RuntimeError, match="başlatılamadı"):
        launcher.wait_until_ready(process, "http://127.0.0.1:8765/", demo=False, timeout=1)


def test_detached_process_flags_match_each_platform(monkeypatch):
    if os.name == "nt":
        assert launcher.detached_options()["creationflags"] & subprocess.CREATE_NO_WINDOW
    else:
        assert launcher.detached_options() == {"start_new_session": True}


def test_error_page_is_visible_and_escapes_error_text(tmp_path, monkeypatch):
    browser = Mock()
    monkeypatch.setattr(launcher.webbrowser, "open", browser)
    launcher.show_error(tmp_path, "<script>bad</script>", browser=True)
    page = tmp_path / "data/runtime/baslatma-hatasi.html"
    assert "&lt;script&gt;" in page.read_text(encoding="utf-8")
    assert "<script>bad" not in page.read_text(encoding="utf-8")
    browser.assert_called_once_with(page.as_uri())


def test_mac_bundle_handles_spaces_unicode_and_apostrophes_and_can_be_reinstalled(tmp_path):
    root = tmp_path / "İhale'nin Projesi"
    desktop = tmp_path / "Desktop"
    bundle = installer.create_macos_shortcut(root, desktop)
    with (bundle / "Contents/Info.plist").open("rb") as file:
        info = plistlib.load(file)
    assert info["CFBundleDisplayName"] == "İhale Bulucu"
    assert info["LSUIElement"] is True
    script = bundle / "Contents/MacOS/launch"
    assert shlex.split(script.read_text(encoding="utf-8").splitlines()[-1]) == [
        "exec",
        str(root / ".venv/bin/python"),
        str(root / "scripts/desktop_launcher.py"),
    ]
    if os.name != "nt":
        assert os.access(script, os.X_OK)
        subprocess.run(["/bin/sh", "-n", str(script)], check=True)
    assert installer.create_macos_shortcut(root, desktop) == bundle
    moved = tmp_path / "Yeni proje klasörü"
    assert installer.create_macos_shortcut(moved, desktop) == bundle
    assert str(moved) in script.read_text(encoding="utf-8")


def test_installer_does_not_overwrite_an_unrelated_desktop_app(tmp_path):
    bundle = tmp_path / "Desktop/İhale Bulucu.app"
    bundle.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="başka bir uygulama"):
        installer.create_macos_shortcut(tmp_path / "project", bundle.parent)


def test_windows_paths_are_data_instead_of_interpolated_powershell(tmp_path, monkeypatch):
    root = tmp_path / "İhale's $project"
    desktop = tmp_path / "OneDrive Desktop"
    result = SimpleNamespace(stdout=str(desktop / "İhale Bulucu.lnk"))
    run = Mock(return_value=result)
    monkeypatch.setattr(installer.subprocess, "run", run)
    assert installer.create_windows_shortcut(root, desktop) == Path(result.stdout)
    command = run.call_args.args[0]
    script = base64.b64decode(command[-1]).decode("utf-16le")
    assert str(root) not in script
    assert "[Environment]::GetFolderPath('Desktop')" in script
    assert run.call_args.kwargs["env"]["IHALE_SHORTCUT_ROOT"] == str(root)
    assert "-ExecutionPolicy" not in command


def test_installer_reuses_an_existing_environment_without_reinstalling(tmp_path, monkeypatch):
    python = launcher.python_path(tmp_path)
    python.parent.mkdir(parents=True)
    python.touch()
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(installer.subprocess, "run", run)
    installer.ensure_environment(tmp_path)
    assert run.call_count == 1
    assert run.call_args.args[0][1:3] == ["-c", "import filelock, tender_enricher"]


def test_installer_prepares_a_missing_environment_and_dependencies(tmp_path, monkeypatch):
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=1 if "-c" in command else 0)

    monkeypatch.setattr(installer.subprocess, "run", run)
    installer.ensure_environment(tmp_path)
    assert commands[0][1:3] == ["-m", "venv"]
    assert commands[-1][1:] == ["-m", "pip", "install", "-e", str(tmp_path)]


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows COM shortcut roundtrip")
def test_native_windows_shortcut_roundtrip(tmp_path):
    root = tmp_path / "İhale Projesi"
    desktop = tmp_path / "OneDrive Desktop"
    (root / ".venv/Scripts").mkdir(parents=True)
    (root / ".venv/Scripts/pythonw.exe").touch()
    (root / "scripts").mkdir()
    (root / "scripts/desktop_launcher.py").touch()
    desktop.mkdir()
    shortcut = installer.create_windows_shortcut(root, desktop)
    assert shortcut.is_file(), list(desktop.iterdir())
    script = """
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:IHALE_TEST_LINK)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
@{target=$s.TargetPath; arguments=$s.Arguments; directory=$s.WorkingDirectory} | ConvertTo-Json
"""
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            base64.b64encode(script.encode("utf-16le")).decode("ascii"),
        ],
        env={**os.environ, "IHALE_TEST_LINK": str(shortcut)},
        capture_output=True,
        check=True,
        encoding="utf-8-sig",
    )
    actual = json.loads(result.stdout)
    assert os.path.normcase(actual["target"]) == os.path.normcase(
        str(root / ".venv/Scripts/pythonw.exe")
    )
    assert actual["directory"] == str(root)
    assert actual["arguments"] == subprocess.list2cmdline(
        [str(root / "scripts/desktop_launcher.py")]
    )
