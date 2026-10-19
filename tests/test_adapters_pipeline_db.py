import io
import json
from datetime import timedelta

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from conftest import ROOT
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tender_enricher.adapters.input.json_file import JsonInputAdapter
from tender_enricher.adapters.output.json_file import JsonOutputAdapter
from tender_enricher.cli import main
from tender_enricher.collectors.company_website.website import CompanyWebsiteCollector
from tender_enricher.collectors.demo import DemoFetcher
from tender_enricher.collectors.ekap.award import PublicAwardCollector
from tender_enricher.collectors.trade_registry.registry import PublicRegistryCollector
from tender_enricher.db.models import Base, EvidenceRow, RunRow, SourceRow, TenderRow
from tender_enricher.models import EnrichmentResult, Issue, TenderInput
from tender_enricher.normalization import normalize_tender
from tender_enricher.pipeline import Pipeline


def demo_pipeline(settings, repository):
    fetcher = DemoFetcher(ROOT / "data/demo")
    return Pipeline(
        [PublicAwardCollector(fetcher, settings)],
        [CompanyWebsiteCollector(fetcher, settings), PublicRegistryCollector(fetcher, settings)],
        repository,
        is_demo=True,
    )


def demo_tender():
    return next(JsonInputAdapter(ROOT / "data/demo/tenders.json").read())


def test_input_array_validates_each_record_and_accepts_single_object(tmp_path, tender):
    path = tmp_path / "in.json"
    path.write_text(json.dumps([{}, tender.model_dump(mode="json")]), encoding="utf-8")
    records = list(JsonInputAdapter(path).read())
    assert isinstance(records[0], Issue)
    assert isinstance(records[1], TenderInput)
    path.write_text(tender.model_dump_json(), encoding="utf-8")
    assert list(JsonInputAdapter(path).read()) == [tender]


def test_output_is_atomic_when_replace_fails(tmp_path, monkeypatch):
    path = tmp_path / "out.json"
    path.write_text("previous", encoding="utf-8")

    def fail(*args):
        raise OSError("disk error")

    monkeypatch.setattr("tender_enricher.adapters.output.json_file.os.replace", fail)
    with pytest.raises(OSError):
        JsonOutputAdapter(path).write([EnrichmentResult(tender_id="2026/1", status="unresolved")])
    assert path.read_text() == "previous"
    assert list(tmp_path.iterdir()) == [path]


def test_demo_pipeline_has_evidence_for_every_non_null_field_and_roundtrips(settings, repository):
    result = demo_pipeline(settings, repository).process(demo_tender())
    assert result.status == "resolved"
    assert result.is_demo
    assert result.winner.city == "İstanbul"  # Tender location was Van.
    assert result.winner.mersis_no is None
    assert result.winner.tax_no is None
    assert result.field_verification["phone"].status == "verified"
    assert result.confidence == 0.9
    assert result.completeness == 0.75
    for field, value in result.winner.model_dump(mode="json").items():
        if value is not None:
            assert any(item.field == field and item.value == str(value) for item in result.evidence)
    assert repository.latest(result.tender_id) == result
    with Session(repository.engine) as session:
        assert session.scalar(select(func.count()).select_from(SourceRow)) == len(result.sources)
        assert session.scalar(select(func.count()).select_from(EvidenceRow)) == len(result.evidence)


def test_provider_exception_does_not_stop_other_providers(settings, repository):
    class Broken:
        name = "broken"

        def collect(self, *args):
            raise RuntimeError("private-key-must-not-leak")

    pipeline = demo_pipeline(settings, repository)
    pipeline.winner_providers = [Broken(), *pipeline.winner_providers]
    pipeline.company_providers = [Broken(), *pipeline.company_providers]
    result = pipeline.process(demo_tender())
    assert result.status == "resolved"
    assert len([issue for issue in result.issues if issue.code == "provider_error"]) == 2
    assert "private-key-must-not-leak" not in result.model_dump_json()


def test_unknown_winner_is_null_and_saved(tender, repository):
    result = Pipeline([], [], repository).process(tender)
    assert result.status == "unresolved" and result.winner is None
    assert result.confidence == 0
    assert repository.latest(tender.tender_id) == result


def test_invalid_normalization_returns_failed_record(tender, repository):
    result = Pipeline([], [], repository).process(tender.model_copy(update={"tender_id": "bad"}))
    assert result.status == "failed"
    assert result.issues[0].code == "invalid_tender_id"


def test_runs_preserve_history_and_duplicate_run_is_idempotent(tender, repository):
    normalized = normalize_tender(tender)
    first = EnrichmentResult(tender_id=tender.tender_id, status="unresolved")
    second = EnrichmentResult(
        tender_id=tender.tender_id,
        status="unresolved",
        processed_at=first.processed_at + timedelta(seconds=1),
    )
    for result in (first, first, second):
        repository.save(normalized, result)
    assert repository.latest(tender.tender_id) == second
    with Session(repository.engine) as session:
        assert session.scalar(select(func.count()).select_from(RunRow)) == 2


def test_transaction_rolls_back_all_rows_on_constraint_failure(settings, repository):
    first = demo_pipeline(settings, repository).process(demo_tender())
    # Deliberately reuse source ids in another run: the FK/PK failure must roll
    # back the new tender and run instead of saving half an enrichment.
    new_tender = demo_tender().model_copy(update={"tender_id": "2026/999"})
    second = first.model_copy(update={"run_id": "new-run", "tender_id": "2026/999"})
    with pytest.raises(IntegrityError):
        repository.save(normalize_tender(new_tender), second)
    assert repository.latest("2026/999") is None
    with Session(repository.engine) as session:
        assert session.get(TenderRow, "2026/999") is None
        assert session.scalar(select(func.count()).select_from(RunRow)) == 1


def test_migration_matches_orm_schema(repository):
    with repository.engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []


def test_migration_can_generate_postgresql_sql_without_database(monkeypatch):
    monkeypatch.setenv("TE_DATABASE_URL", "postgresql+psycopg://user:password@localhost/tenders")
    stream = io.StringIO()
    config = Config(str(ROOT / "alembic.ini"), output_buffer=stream)
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(config, "head", sql=True)
    sql = stream.getvalue()
    assert "TIMESTAMP WITH TIME ZONE" in sql
    assert "CREATE TABLE evidence" in sql
    assert "password" not in sql


def test_cli_demo_and_export(tmp_path):
    database = f"sqlite:///{tmp_path / 'demo.db'}"
    output = tmp_path / "demo.json"
    assert main(["demo", "--database-url", database, "--output", str(output)]) == 0
    records = json.loads(output.read_text())
    assert [record["status"] for record in records] == ["resolved", "unresolved"]
    assert all(record["is_demo"] for record in records)
    exported = tmp_path / "exported.json"
    assert (
        main(
            [
                "export",
                "--database-url",
                database,
                "--tender-id",
                "2026/123456",
                "--output",
                str(exported),
            ]
        )
        == 0
    )
    assert json.loads(exported.read_text())[0] == records[0]


def test_cli_configuration_error_does_not_expose_connection_secret(capsys):
    assert main(["init-db", "--database-url", "invalid PRIVATE_SECRET"]) == 2
    assert "PRIVATE_SECRET" not in capsys.readouterr().out


def test_pipeline_reports_database_failure_without_losing_collected_data(settings, repository):
    class BrokenRepository:
        def save(self, *args):
            raise RuntimeError("db-private-secret")

    pipeline = demo_pipeline(settings, repository)
    pipeline.repository = BrokenRepository()
    result = pipeline.process(demo_tender())
    assert result.status == "failed"
    assert result.winner.phone is not None
    assert result.evidence
    assert result.issues[-1].code == "persistence_failed"
    assert "db-private-secret" not in result.model_dump_json()


def test_pipeline_conflicting_contact_is_null_and_requires_review(settings, repository):
    from tender_enricher.collectors.parsing import profile_from_values
    from tender_enricher.evidence import make_source
    from tender_enricher.models import Collection, CompanyCandidate, CompanyField, SourceType

    class ConflictingContact:
        name = "conflicting_contact"

        def collect(self, tender, winner):
            source = make_source(
                "https://other.demo.test/",
                "https://other.demo.test/",
                "different public phone",
                SourceType.NEWS,
                is_demo=True,
            )
            company, evidence = profile_from_values(
                {
                    "company_name": (winner.company_name, "h1"),
                    "website": (str(winner.website), "a"),
                    "phone": ("+902120000001", "p"),
                },
                source,
            )
            return Collection(
                sources=[source], candidates=[CompanyCandidate(company=company, evidence=evidence)]
            )

    pipeline = demo_pipeline(settings, repository)
    pipeline.company_providers = [*pipeline.company_providers, ConflictingContact()]
    result = pipeline.process(demo_tender())
    assert result.status == "review_required"
    assert result.winner.phone is None
    assert result.field_verification[CompanyField.PHONE].status == "conflicting"
    assert len(result.field_verification[CompanyField.PHONE].alternatives) == 2


def test_cli_continues_after_invalid_record(tmp_path, tender):
    source, output = tmp_path / "in.json", tmp_path / "out.json"
    source.write_text(json.dumps([{}, tender.model_dump(mode="json")]))
    assert (
        main(
            [
                "run",
                "--input",
                str(source),
                "--output",
                str(output),
                "--database-url",
                f"sqlite:///{tmp_path / 'test.db'}",
            ]
        )
        == 2
    )
    records = json.loads(output.read_text())
    assert [record["status"] for record in records] == ["failed", "unresolved"]
    assert records[1]["winner"] is None
