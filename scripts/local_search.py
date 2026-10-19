"""Start/check/stop the optional local metasearch service without paid API keys."""

import argparse
import json
import secrets
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, build_opener

from dotenv import set_key

from tender_enricher.config import Settings

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "infra/search/compose.yaml"
LOCAL_URL = "http://127.0.0.1:8080"
INSTANCE = "IhaleSystem Yerel Arama"
ENGINES = ["brave", "duckduckgo", "yahoo"]


def run(*command: str, timeout: int = 300) -> None:
    subprocess.run(command, cwd=ROOT, check=True, timeout=timeout)


def ensure_docker() -> None:
    if not shutil.which("docker"):
        raise RuntimeError("Docker kurulu değil. Önce resmî Docker Desktop uygulamasını kurun.")
    ready = (
        subprocess.run(["docker", "info"], capture_output=True, check=False, timeout=15).returncode
        == 0
    )
    if not ready:
        if sys.platform not in {"darwin", "win32"}:
            raise RuntimeError("Docker servisi çalışmıyor; başlatıp tekrar deneyin.")
        run("docker", "desktop", "start", "--timeout", "45", timeout=60)


def compose(*arguments: str) -> None:
    run("docker", "compose", "-f", str(COMPOSE), *arguments)


def request_json(path: str) -> dict:
    # This helper only talks to its fixed loopback endpoint, never a public instance.
    with build_opener(ProxyHandler({})).open(LOCAL_URL + path, timeout=20) as response:
        data = json.load(response)
    if not isinstance(data, dict):
        raise RuntimeError("Yerel arama servisi geçerli JSON döndürmedi.")
    return data


def verify_service() -> dict:
    data = request_json("/config")
    if data.get("instance_name") != INSTANCE:
        raise RuntimeError("8080 portunda başka bir servis var; yerel ayar değiştirilmedi.")
    enabled = {engine["name"] for engine in data["engines"] if engine.get("enabled")}
    if not set(ENGINES).issubset(enabled):
        raise RuntimeError("Yerel arama ayarında gerekli üç motor etkin değil.")
    return data


def prepare_config() -> None:
    destination = ROOT / "data/runtime/search/config/settings.yml"
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        template = (ROOT / "infra/search/settings.yml.example").read_text(encoding="utf-8")
        destination.write_text(
            template.replace("__SEARXNG_SECRET__", secrets.token_hex(32)), encoding="utf-8"
        )
        destination.chmod(0o600)


def configure_app(settings: Settings) -> None:
    env = ROOT / ".env"
    if not env.exists():
        shutil.copyfile(ROOT / ".env.example", env)
        env.chmod(0o600)
    providers = list(settings.search_providers)
    if "searxng" not in providers:
        providers.append("searxng")
    set_key(str(env), "TE_SEARXNG_URL", LOCAL_URL)
    set_key(str(env), "TE_SEARXNG_ENGINES", json.dumps(ENGINES))
    set_key(str(env), "TE_SEARCH_PROVIDERS", json.dumps(providers))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["start", "ensure", "check", "status", "stop"])
    args = parser.parse_args()
    try:
        settings = Settings(_env_file=ROOT / ".env")
        local = str(settings.searxng_url or "").rstrip("/") == LOCAL_URL
        if args.command == "ensure" and (not local or "searxng" not in settings.search_providers):
            return 0
        if args.command in {"start", "ensure"}:
            if settings.searxng_url and not local:
                raise RuntimeError("Başka SearXNG sunucusu ayarlı; mevcut adres korunuyor.")
            ensure_docker()
            prepare_config()
            compose("up", "-d", "--wait", "--wait-timeout", "180")
            verify_service()
            if args.command == "start":
                configure_app(settings)
            print("Yerel arama hazır: Brave, DuckDuckGo, Yahoo — " + LOCAL_URL)
        elif args.command == "stop":
            compose("stop")
        elif args.command == "status":
            verify_service()
            print("Yerel arama servisi erişilebilir; üç motor yapılandırıldı.")
        else:
            verify_service()
            query = urlencode(
                {
                    "q": "Türkiye inşaat şirketleri kurumsal iletişim",
                    "format": "json",
                    "language": "tr-TR",
                    "categories": "general",
                    "engines": ",".join(ENGINES),
                }
            )
            data = request_json("/search?" + query)
            counts = Counter(
                engine for row in data.get("results", []) for engine in row.get("engines", [])
            )
            print(json.dumps({"results": len(data.get("results", [])), "engines": counts}))
            if len(set(counts) & set(ENGINES)) < 2:
                raise RuntimeError("Gerçek sorguda en az iki motordan sonuç alınamadı.")
        return 0
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
    except (OSError, URLError, ValueError, KeyError, subprocess.SubprocessError):
        print("Yerel arama başlatılamadı; Docker ve servis durumunu kontrol edin.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
