"""Open the local panel, starting one detached application process when needed."""

import argparse
import html
import json
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener

from filelock import FileLock, Timeout

ROOT = Path(__file__).resolve().parents[1]


def python_path(root: Path) -> Path:
    return root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def panel_ready(url: str, *, demo: bool = False) -> bool:
    try:
        with build_opener(ProxyHandler({})).open(url + "api/status", timeout=2) as response:
            value = json.loads(response.read(262144))
        return (
            isinstance(value, dict)
            and value.get("is_demo") is demo
            and isinstance(value.get("configured_sources"), list)
            and isinstance(value.get("enrichment"), dict)
            and isinstance(value["enrichment"].get("counts"), dict)
        )
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return False


def detached_options() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def wait_until_ready(process: subprocess.Popen, url: str, *, demo: bool, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if panel_ready(url, demo=demo):
            return
        if process.poll() is not None:
            raise RuntimeError("Uygulama başlatılamadı. Günlük dosyasını kontrol edin.")
        time.sleep(0.3)
    raise RuntimeError("Uygulama henüz hazır değil. Biraz sonra simgeye tekrar çift tıklayın.")


def launch(
    root: Path,
    *,
    port: int = 8765,
    demo: bool = False,
    data_dir: Path | None = None,
    no_auto: bool = False,
    browser: bool = True,
) -> str:
    url = f"http://127.0.0.1:{port}/"
    runtime = root / "data/runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / "desktop-launcher.log").open("ab", buffering=0) as log:
        log.write(f"\nDesktop launcher requested: {url}\n".encode())
    if not panel_ready(url, demo=demo):
        with FileLock(runtime / f".desktop-{port}.lock", timeout=300):
            if not panel_ready(url, demo=demo):
                python = python_path(root)
                if not python.is_file():
                    raise RuntimeError(
                        "Önce proje klasöründeki Masaustu_Kisayolu dosyasını çalıştırın."
                    )
                with (runtime / "desktop-launcher.log").open("ab", buffering=0) as log:
                    if not demo:
                        log.write(b"\n--- Local search startup ---\n")
                        try:
                            subprocess.run(
                                [str(python), str(root / "scripts/local_search.py"), "ensure"],
                                cwd=root,
                                stdin=subprocess.DEVNULL,
                                stdout=log,
                                stderr=subprocess.STDOUT,
                                timeout=240,
                                check=True,
                                **(
                                    {"creationflags": subprocess.CREATE_NO_WINDOW}
                                    if os.name == "nt"
                                    else {}
                                ),
                            )
                        except (OSError, subprocess.SubprocessError) as error:
                            raise RuntimeError(
                                "Arama servisi açılamadı. Docker Desktop'ı açıp tekrar deneyin."
                            ) from error
                    command = [str(python), str(root / "app.py"), "--port", str(port)]
                    if demo:
                        command.append("--demo")
                    if no_auto:
                        command.append("--no-auto")
                    if data_dir:
                        command.extend(["--data-dir", str(data_dir.resolve())])
                    log.write(b"\n--- IhaleSystem startup ---\n")
                    process = subprocess.Popen(
                        command,
                        cwd=root,
                        stdin=subprocess.DEVNULL,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        **detached_options(),
                    )
                wait_until_ready(process, url, demo=demo, timeout=60)
    if browser:
        if not webbrowser.open(url):
            raise RuntimeError(f"Panel hazır; tarayıcıda bu adresi açın: {url}")
    return url


def show_error(root: Path, message: str, *, browser: bool) -> None:
    runtime = root / "data/runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    page = runtime / "baslatma-hatasi.html"
    page.write_text(
        '<!doctype html><html lang="tr"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>İhale Bulucu açılamadı</title>"
        '<body style="font:18px system-ui;max-width:650px;margin:60px auto;padding:20px">'
        "<h1>İhale Bulucu açılamadı</h1><p>" + html.escape(message) + "</p>"
        "<p>Ayrıntılı günlük: <code>"
        + html.escape(str(runtime / "desktop-launcher.log"))
        + "</code></p></body></html>",
        encoding="utf-8",
    )
    if sys.stderr is not None:
        print(message, file=sys.stderr)
    if browser:
        webbrowser.open(page.as_uri())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--no-auto", action="store_true")
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Geçerli bir port gerekli.")
    try:
        launch(
            ROOT,
            port=args.port,
            demo=args.demo,
            data_dir=args.data_dir,
            no_auto=args.no_auto,
            browser=not args.no_browser,
        )
        return 0
    except Timeout:
        message = "Başlatma sürüyor. Biraz sonra masaüstü simgesine tekrar çift tıklayın."
    except RuntimeError as error:
        message = str(error)
    except (OSError, subprocess.SubprocessError):
        message = "Uygulama açılamadı. Proje klasörünü ve Python kurulumunu kontrol edin."
    show_error(ROOT, message, browser=not args.no_browser)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
