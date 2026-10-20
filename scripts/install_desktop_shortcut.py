"""One-time native desktop shortcut installation for macOS and Windows."""

from __future__ import annotations

import base64
import os
import plistlib
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "İhale Bulucu"


def ensure_environment(root: Path) -> None:
    if sys.version_info < (3, 11):  # noqa: UP036 — bootstrap may use the system Python.
        raise RuntimeError("Python 3.11 veya üzerini kurup tekrar deneyin.")
    python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        print("İlk kurulum: Python çalışma ortamı hazırlanıyor…", flush=True)
        subprocess.run([sys.executable, "-m", "venv", str(root / ".venv")], check=True)
    result = subprocess.run(
        [str(python), "-c", "import filelock, tender_enricher"],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode:
        print("İlk kurulum: uygulama bağımlılıkları yükleniyor…", flush=True)
        subprocess.run([str(python), "-m", "pip", "install", "-e", str(root)], check=True)


def create_macos_shortcut(root: Path, desktop: Path) -> Path:
    bundle = desktop / (NAME + ".app")
    marker = bundle / "Contents/Resources/ihalesystem-project.txt"
    if bundle.exists():
        try:
            with (bundle / "Contents/Info.plist").open("rb") as file:
                previous = plistlib.load(file)
            owned = (
                marker.is_file()
                and previous.get("CFBundleIdentifier") == "com.ihalesystem.launcher"
            )
        except (OSError, ValueError):
            owned = False
        if not owned:
            raise RuntimeError("Masaüstünde aynı isimli başka bir uygulama var; korunuyor.")
    executable = bundle / "Contents/MacOS/launch"
    executable.parent.mkdir(parents=True, exist_ok=True)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(str(root), encoding="utf-8")
    executable.write_text(
        '#!/bin/sh\nPATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"\n'
        "export PATH\nexec "
        + shlex.quote(str(root / ".venv/bin/python"))
        + " "
        + shlex.quote(str(root / "scripts/desktop_launcher.py"))
        + "\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    with (bundle / "Contents/Info.plist").open("wb") as file:
        plistlib.dump(
            {
                "CFBundleExecutable": "launch",
                "CFBundleIdentifier": "com.ihalesystem.launcher",
                "CFBundleName": NAME,
                "CFBundleDisplayName": NAME,
                "CFBundlePackageType": "APPL",
                "CFBundleVersion": "1",
                "CFBundleShortVersionString": "1.0",
                "LSUIElement": True,
                "NSHighResolutionCapable": True,
            },
            file,
        )
    return bundle


def create_windows_shortcut(root: Path, desktop: Path | None = None) -> Path:
    # Pass paths as environment values, not interpolated PowerShell source.
    script = """
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$desktop = if ($env:IHALE_SHORTCUT_DESKTOP) { $env:IHALE_SHORTCUT_DESKTOP } else {
    [Environment]::GetFolderPath('Desktop')
}
$path = Join-Path $desktop 'İhale Bulucu.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($path)
if ((Test-Path $path) -and ($shortcut.WorkingDirectory -ne $env:IHALE_SHORTCUT_ROOT) -and
    ($shortcut.Description -ne 'IhaleSystem masaustu baslaticisi')) {
    throw 'Masaustunde ayni isimli baska bir kisayol var; korunuyor.'
}
$shortcut.TargetPath = Join-Path $env:IHALE_SHORTCUT_ROOT '.venv\\Scripts\\pythonw.exe'
$shortcut.Arguments = $env:IHALE_SHORTCUT_ARGUMENTS
$shortcut.WorkingDirectory = $env:IHALE_SHORTCUT_ROOT
$shortcut.Description = 'IhaleSystem masaustu baslaticisi'
$shortcut.WindowStyle = 7
$shortcut.Save()
[Console]::Write($path)
"""
    environment = {
        **os.environ,
        "IHALE_SHORTCUT_ROOT": str(root),
        "IHALE_SHORTCUT_DESKTOP": str(desktop) if desktop else "",
        "IHALE_SHORTCUT_ARGUMENTS": subprocess.list2cmdline(
            [str(root / "scripts/desktop_launcher.py")]
        ),
    }
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            base64.b64encode(script.encode("utf-16le")).decode("ascii"),
        ],
        env=environment,
        capture_output=True,
        check=True,
        encoding="utf-8-sig",
    )
    return Path(result.stdout.strip())


def main() -> int:
    try:
        if sys.platform not in {"darwin", "win32"}:
            raise RuntimeError("Masaüstü kısayolu Mac ve Windows için hazırlanmıştır.")
        ensure_environment(ROOT)
        path = (
            create_macos_shortcut(ROOT, Path.home() / "Desktop")
            if sys.platform == "darwin"
            else create_windows_shortcut(ROOT)
        )
        print(f"Kısayol hazır: {path}\nBundan sonra masaüstündeki simgeye çift tıklayın.")
        return 0
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
    except (OSError, subprocess.SubprocessError):
        print(
            "Kısayol oluşturulamadı. Python kurulumunu ve klasör izinlerini kontrol edin.",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
