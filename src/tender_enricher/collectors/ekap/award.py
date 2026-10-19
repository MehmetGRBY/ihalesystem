"""Labelled public award pages; no assumption about EKAP portal DOM or login."""

from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from tender_enricher.collectors.contracts import PageFetcher
from tender_enricher.collectors.parsing import labeled_values, profile_from_values
from tender_enricher.collectors.search.multi import search_issues
from tender_enricher.config import Settings
from tender_enricher.enrichment import provider_failure
from tender_enricher.evidence import make_evidence, make_source
from tender_enricher.models import (
    Collection,
    CompanyField,
    Issue,
    NormalizedTender,
    SourceType,
    WinnerClaim,
)
from tender_enricher.normalization import company_key, tender_id, text_key
from tender_enricher.ports import SearchProvider


class PublicAwardCollector:
    name = "public_award"

    def __init__(
        self, fetcher: PageFetcher, settings: Settings, search: SearchProvider | None = None
    ) -> None:
        self.fetcher, self.settings, self.search = fetcher, settings, search

    def collect(self, tender: NormalizedTender) -> Collection:
        self.fetcher.begin_tender()
        urls = [str(url) for url in tender.award_urls]
        result = Collection()
        if self.search:
            try:
                urls.extend(
                    self.search.search(
                        f'"{tender.tender_id}" "{tender.title}" yüklenici ihale sonucu',
                    )
                )
            except Exception as error:
                result.issues.append(provider_failure("search", "winner_collection", error))
            result.issues.extend(search_issues(self.search, "winner_collection"))
        for url in list(dict.fromkeys(urls))[: self.settings.max_pages_per_tender]:
            try:
                self._collect_url(url, tender, result)
            except Exception as error:
                result.issues.append(provider_failure(self.name, "winner_collection", error))
        return result

    def _collect_url(self, url: str, tender: NormalizedTender, result: Collection) -> None:
        document = self.fetcher.fetch(url)
        kind = (
            SourceType.OFFICIAL_AWARD
            if urlsplit(document.final_url).hostname in self.settings.official_award_hosts
            else SourceType.NEWS
        )
        source = make_source(url, document.final_url, document.body, kind, is_demo=document.is_demo)
        result.sources.append(source)
        soup = BeautifulSoup(document.body, "lxml")
        values = labeled_values(soup)
        ids: set[str] = set()
        for value, _ in values.get("tender_id", []):
            try:
                ids.add(tender_id(value))
            except ValueError:
                continue
        if ids != {tender.tender_id}:
            result.issues.append(
                Issue(
                    stage="winner_collection",
                    code="unsupported_award_page",
                    provider=self.name,
                    message="Page needs one exact labeled tender id and one explicit winner.",
                )
            )
            return
        names = {name for name, _ in values.get("winner", [])}
        text = text_key(soup.get_text(" ", strip=True))
        ambiguous = any(
            marker in text
            for marker in (
                "ortak girisim",
                "is ortakligi",
                "konsorsiyum",
                "ihale iptal",
                "iptal edildi",
            )
        )
        ambiguous = ambiguous or any(
            sum(token in {"as", "ltd"} for token in company_key(name).split()) > 1 for name in names
        )
        if len(names) != 1 or ambiguous:
            result.issues.append(
                Issue(
                    stage="winner_collection",
                    code="award_ambiguous",
                    provider=self.name,
                    message="Multiple winners, cancellation or joint venture needs manual review.",
                )
            )
            return
        name, locator = values["winner"][0]
        company_values = {"company_name": (name, locator)}
        extra_values: list[tuple[str, tuple[str, str]]] = []
        # Generic İl/Adres can describe the project or authority. Read identity only
        # from an explicitly delimited contractor-details section.
        contractor = soup.select_one("#winner-details, #yuklenici-bilgileri")
        if contractor:
            scoped = labeled_values(BeautifulSoup(str(contractor), "lxml"))
            for field, observations in scoped.items():
                if field not in {"winner", "tender_id", "company_name"}:
                    company_values[field] = observations[0]
                    extra_values.extend((field, observation) for observation in observations[1:])
        profile, evidence = profile_from_values(company_values, source)
        for field, observation in extra_values:
            _, extra_evidence = profile_from_values({field: observation}, source)
            evidence.extend(extra_evidence)
        evidence.append(
            make_evidence(
                CompanyField.WINNER,
                name,
                source,
                locator,
                f"İKN: {tender.tender_id}; Yüklenici: {name}",
            )
        )
        result.winner_claims.append(
            WinnerClaim(
                tender_id=tender.tender_id,
                company=profile,
                evidence=evidence,
            )
        )
