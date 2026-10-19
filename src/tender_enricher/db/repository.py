from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from tender_enricher.db.models import CompanyRow, EvidenceRow, RunRow, SourceRow, TenderRow
from tender_enricher.models import EnrichmentResult, NormalizedTender


class SqlAlchemyResultRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def save(self, tender: NormalizedTender, result: EnrichmentResult) -> None:
        # One transaction includes tender, run, verified profile and raw observations.
        # A duplicate run_id is idempotent; a new run preserves the previous result.
        with Session(self.engine) as session, session.begin():
            if session.get(RunRow, result.run_id):
                return
            row = session.get(TenderRow, tender.tender_id)
            if row is None:
                row = TenderRow(tender_id=tender.tender_id, payload=tender.model_dump(mode="json"))
                session.add(row)
            else:
                row.payload = tender.model_dump(mode="json")
            session.flush()
            session.add(
                RunRow(
                    run_id=result.run_id,
                    tender_id=tender.tender_id,
                    status=result.status,
                    confidence=result.confidence,
                    processed_at=result.processed_at,
                    payload=result.model_dump(mode="json"),
                )
            )
            session.flush()
            if result.winner:
                session.add(
                    CompanyRow(run_id=result.run_id, **result.winner.model_dump(mode="json"))
                )
            for source in result.sources:
                session.add(
                    SourceRow(
                        source_id=source.id,
                        run_id=result.run_id,
                        payload=source.model_dump(mode="json"),
                    )
                )
            session.flush()
            for evidence in result.evidence:
                session.add(
                    EvidenceRow(
                        evidence_id=evidence.id,
                        run_id=result.run_id,
                        source_id=evidence.source_id,
                        field=evidence.field,
                        value=evidence.value,
                        excerpt=evidence.excerpt,
                        locator=evidence.locator,
                    )
                )

    def latest(self, tender_id: str) -> EnrichmentResult | None:
        with Session(self.engine) as session:
            row = session.scalar(
                select(RunRow)
                .where(RunRow.tender_id == tender_id)
                .order_by(RunRow.processed_at.desc(), RunRow.run_id.desc())
                .limit(1)
            )
            return EnrichmentResult.model_validate(row.payload) if row else None
