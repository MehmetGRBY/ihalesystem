"""python scripts/backup.py verify SNAPSHOT | restore SNAPSHOT NEW_DIRECTORY"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from system_backup import restore_snapshot, verify  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="IhaleSystem yedek doğrulama / geri yükleme")
    parser.add_argument("action", choices=["verify", "restore"])
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("destination", type=Path, nargs="?")
    args = parser.parse_args()
    if args.action == "restore":
        if args.destination is None:
            parser.error("Geri yükleme için yeni hedef klasörü gerekli.")
        print(restore_snapshot(args.snapshot, args.destination))
    else:
        print(f"Doğrulandı: {len(verify(args.snapshot)['files'])} dosya")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError):
        print("Yedek doğrulanamadı veya hedef kullanılamıyor.", file=sys.stderr)
        raise SystemExit(1) from None
