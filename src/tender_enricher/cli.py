import argparse
import json
from collections import Counter
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from tender_enricher.adapters.input.json_file import JsonInputAdapter
from tender_enricher.adapters.output.json_file import JsonOutputAdapter
from tender_enricher.collectors.browser import BrowserClient
from tender_enricher.collectors.company_website.website import CompanyWebsiteCollector
from tender_enricher.collectors.contracts import PageFetcher
from tender_enricher.collectors.demo import DemoFetcher
from tender_enricher.collectors.ekap.award import PublicAwardCollector
from tender_enricher.collectors.search.brave import BraveSearchProvider
from tender_enricher.collectors.trade_registry.registry import PublicRegistryCollector
from tender_enricher.collectors.web import WebClient
from tender_enricher.config import Settings
from tender_enricher.db.migrate import upgrade_database
from tender_enricher.db.repository import SqlAlchemyResultRepository
from tender_enricher.db.session import make_engine
from tender_enricher.logging_config import configure_logging
from tender_enricher.models import EnrichmentResult, Issue, TenderInput
from tender_enricher.pipeline import Pipeline


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(
        description="Enrich existing tender records using public evidence."
    )
    commands = cli.add_subparsers(dest="command", required=True)
    commands.add_parser("schema", help="Regenerate versioned JSON schemas")
    init = commands.add_parser("init-db", help="Apply Alembic migrations")
    init.add_argument("--database-url")
    for name in ("run", "demo"):
        run = commands.add_parser(name)
        run.add_argument("--input", type=Path)
        run.add_argument("--output", type=Path)
        run.add_argument("--database-url")
        if name == "run":
            run.add_argument(
                "--browser", action="store_true", help="Use opt-in Playwright renderer"
            )
    export = commands.add_parser("export", help="Export the latest stored run")
    export.add_argument("--tender-id", required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--database-url")
    return cli


def dispatch(args: argparse.Namespace) -> int:
    settings = Settings()
    root = Path(__file__).resolve().parents[2]
    if args.command == "schema":
        for name, model in (
            ("tender-input.v1", TenderInput),
            ("enrichment-result.v1", EnrichmentResult),
        ):
            destination = root / "schemas" / (name + ".json")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return 0
    database_url = args.database_url or (
        "sqlite:///data/demo.db" if args.command == "demo" else settings.database_url
    )
    engine = make_engine(database_url)
    try:
        upgrade_database(engine)
        repository = SqlAlchemyResultRepository(engine)
        if args.command == "init-db":
            print("Database migrated to head.")
            return 0
        if args.command == "export":
            result = repository.latest(args.tender_id)
            if result is None:
                print("No stored run for the requested tender.")
                return 2
            JsonOutputAdapter(args.output).write([result])
            return 0
        return execute(args, settings, root, repository)
    except (OSError, ValueError) as error:
        # Do not print settings/connection strings, validation inputs or API keys.
        print(f"Command failed ({type(error).__name__}). Check input paths and configuration.")
        return 2
    finally:
        engine.dispose()


def execute(
    args: argparse.Namespace, settings: Settings, root: Path, repository: SqlAlchemyResultRepository
) -> int:
    demo = args.command == "demo"
    input_path = args.input or (root / "data/demo/tenders.json" if demo else settings.input_path)
    output_path = args.output or (
        Path("data/outbox/demo-results.json") if demo else settings.output_path
    )
    fetcher: PageFetcher
    search: BraveSearchProvider | None = None
    if demo:
        fetcher = DemoFetcher(root / "data/demo")
        settings = settings.model_copy(
            update={
                "official_award_hosts": ["awards.demo.test"],
                "registry_hosts": ["registry.demo.test"],
            }
        )
    else:
        web = WebClient(settings)
        fetcher = BrowserClient(web) if args.browser or settings.browser_enabled else web
        if settings.brave_api_key and settings.brave_api_key.get_secret_value():
            search = BraveSearchProvider(settings)
    pipeline = Pipeline(
        [PublicAwardCollector(fetcher, settings, search)],
        [
            CompanyWebsiteCollector(fetcher, settings, search),
            PublicRegistryCollector(fetcher, settings),
        ],
        repository,
        is_demo=demo,
    )
    try:
        results: list[EnrichmentResult] = []
        for index, record in enumerate(JsonInputAdapter(input_path).read()):
            if isinstance(record, Issue):
                results.append(
                    EnrichmentResult(
                        tender_id=f"invalid-record-{index + 1}",
                        status="failed",
                        issues=[record],
                        is_demo=demo,
                    )
                )
            else:
                results.append(pipeline.process(record))
        JsonOutputAdapter(output_path).write(results)
        print(
            json.dumps(
                {
                    "records": len(results),
                    "statuses": dict(Counter(result.status for result in results)),
                    "output": str(output_path),
                    "is_demo": demo,
                },
                ensure_ascii=False,
            )
        )
        return 2 if any(result.status == "failed" for result in results) else 0
    finally:
        fetcher.close()
        if search:
            search.close()


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    configure_logging()
    try:
        return dispatch(args)
    except (OSError, ValueError, SQLAlchemyError) as error:
        print(f"Command failed ({type(error).__name__}). Check input paths and configuration.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
