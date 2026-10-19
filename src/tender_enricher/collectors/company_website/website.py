from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from tender_enricher.collectors.company_website.html_contacts import public_contacts
from tender_enricher.collectors.contracts import PageFetcher
from tender_enricher.collectors.parsing import (
    labeled_values,
    organization_values,
    organizations,
    profile_from_values,
)
from tender_enricher.config import Settings
from tender_enricher.enrichment import provider_failure
from tender_enricher.evidence import make_source, publisher_group
from tender_enricher.models import (
    Collection,
    CompanyCandidate,
    CompanyProfile,
    Issue,
    NormalizedTender,
    Source,
    SourceType,
)
from tender_enricher.ports import SearchProvider


def parse_companies(body: str, source: Source) -> list[CompanyCandidate]:
    soup = BeautifulSoup(body, "lxml")
    for hidden_node in soup.select(
        "script:not([type='application/ld+json']), style, form, nav, [hidden], "
        "[aria-hidden='true'], [style*='display:none'], [style*='display: none']"
    ):
        hidden_node.decompose()
    candidates: list[CompanyCandidate] = []
    for node, locator in organizations(soup):
        profile, evidence = profile_from_values(organization_values(node, locator), source)
        if profile.company_name:
            candidates.append(CompanyCandidate(company=profile, evidence=evidence))
    labels = labeled_values(soup)
    if len({name for name, _ in labels.get("company_name", [])}) == 1:
        # Preserve multiple contact values as separate evidence, even when the
        # profile itself has only one slot. Verification will detect conflict.
        fields = {field: items[0] for field, items in labels.items() if items}
        profile, evidence = profile_from_values(fields, source)
        for field, observations in labels.items():
            for value in observations[1:]:
                _, extra = profile_from_values({field: value}, source)
                evidence.extend(extra)
        if profile.company_name:
            candidates.append(CompanyCandidate(company=profile, evidence=evidence))
    return candidates or public_contacts(soup, source)


class CompanyWebsiteCollector:
    name = "company_website"

    def __init__(
        self, fetcher: PageFetcher, settings: Settings, search: SearchProvider | None = None
    ) -> None:
        self.fetcher, self.settings, self.search = fetcher, settings, search

    def collect(self, tender: NormalizedTender, winner: CompanyProfile) -> Collection:
        urls = [str(url) for url in tender.company_urls]
        if winner.website:
            urls.append(str(winner.website))
        result = Collection()
        if self.search and winner.company_name:
            try:
                urls.extend(self.search.search(f'"{winner.company_name}" iletişim telefon'))
            except Exception as error:
                result.issues.append(provider_failure("search", "enrichment", error))
        for url in list(dict.fromkeys(urls))[: self.settings.max_pages_per_tender]:
            try:
                document = self.fetcher.fetch(url)
                # A directory mentioning a corporate URL is not that company's site.
                source = make_source(
                    url,
                    document.final_url,
                    document.body,
                    SourceType.NEWS,
                    is_demo=document.is_demo,
                )
                if urlsplit(document.final_url).hostname in self.settings.registry_hosts:
                    source.source_type = SourceType.PUBLIC_REGISTRY
                candidates = parse_companies(document.body, source)
                if (
                    source.source_type != SourceType.PUBLIC_REGISTRY
                    and candidates
                    and all(
                        item.company.website
                        and publisher_group(str(item.company.website))
                        == publisher_group(document.final_url)
                        for item in candidates
                    )
                ):
                    source.source_type = SourceType.COMPANY_WEBSITE
                result.sources.append(source)
                result.candidates.extend(candidates)
                if not candidates:
                    result.issues.append(
                        Issue(
                            stage="enrichment",
                            code="unsupported_company_page",
                            provider=self.name,
                            message="Page has no supported explicit company identity.",
                        )
                    )
            except Exception as error:
                result.issues.append(provider_failure(self.name, "enrichment", error))
        return result
