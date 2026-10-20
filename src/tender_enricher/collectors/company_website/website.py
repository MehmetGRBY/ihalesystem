from collections import Counter, deque
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from tender_enricher.addressing import address_supports_identity
from tender_enricher.collectors.company_website.html_contacts import public_contacts, site_identity
from tender_enricher.collectors.contracts import PageFetcher
from tender_enricher.collectors.parsing import (
    labeled_values,
    organization_values,
    organizations,
    profile_from_values,
)
from tender_enricher.collectors.search.multi import search_issues
from tender_enricher.config import Settings
from tender_enricher.enrichment import provider_failure
from tender_enricher.errors import CollectionError
from tender_enricher.evidence import make_source, publisher_group
from tender_enricher.matching import match_company
from tender_enricher.models import (
    Collection,
    CompanyCandidate,
    CompanyField,
    CompanyProfile,
    Issue,
    NormalizedTender,
    Source,
    SourceType,
)
from tender_enricher.normalization import company_key, domain, text_key
from tender_enricher.ports import SearchProvider


def identity_links(body: str, base: str) -> list[str]:
    """Only observed same-host identity links, never generated URLs or external policies."""
    soup = BeautifulSoup(body, "lxml")
    for node in soup.select(
        "form, script, style, [hidden], [aria-hidden='true'], "
        "[style*='display:none'], [style*='display: none']"
    ):
        node.decompose()
    links: dict[str, int] = {}
    for link in soup.select("a[href]"):
        try:
            parsed = urlsplit(urljoin(base, str(link["href"])))
            if (
                parsed.scheme not in {"http", "https"}
                or parsed.username
                or parsed.password
                or parsed.port not in {None, 80, 443}
                or domain(urlunsplit(parsed)) != domain(base)
            ):
                continue
            caption = link.get_text(" ", strip=True)
            if len(caption) > 80 or len(caption.split()) > 8:
                caption = ""  # Malformed menu/logo links can accidentally enclose the page.
            label = text_key(parsed.path + " " + caption)
            priority = next(
                (
                    i
                    for i, markers in enumerate(
                        (
                            ("kvkk", "kunye", "imprint", "privacy", "gizlilik"),
                            ("hakkimizda", "kurumsal", "about"),
                        )
                    )
                    if any(marker in label.split() for marker in markers)
                ),
                None,
            )
            if priority is not None:
                url = urlunsplit(parsed._replace(fragment=""))
                links[url] = min(priority, links.get(url, priority))
        except ValueError:
            continue
    return sorted(links, key=lambda url: links[url])[:2]


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


def link_contact_identity(
    pages: list[tuple[Source, str, list[CompanyCandidate]]], winner: CompanyProfile
) -> list[CompanyCandidate]:
    """Bind a short-brand contact page to its directly linked, matching legal owner.

    Both pages must publish the same detailed postal identity and brand. Evidence
    remains on its actual page; same-site pages never count as independent publishers.
    """
    linked = []
    for source, body, candidates in pages:
        if source.source_type != SourceType.COMPANY_WEBSITE:
            continue
        brand = site_identity(BeautifulSoup(body, "lxml"))
        links = identity_links(body, str(source.final_url))
        owners: list[CompanyCandidate] = []
        for legal_source, legal_body, legal_candidates in pages:
            legal_brand = site_identity(BeautifulSoup(legal_body, "lxml"))
            if (
                legal_source.source_type != SourceType.COMPANY_WEBSITE
                or str(legal_source.url) not in links
                or domain(str(legal_source.final_url)) != domain(str(source.final_url))
                or not brand
                or not legal_brand
                or text_key(brand[0]) != text_key(legal_brand[0])
            ):
                continue
            owners.extend(
                item
                for item in legal_candidates
                if any(
                    proof.field == CompanyField.COMPANY_NAME
                    and proof.locator.startswith("company-identity[")
                    for proof in item.evidence
                )
            )
        if len({company_key(item.company.company_name) for item in owners}) != 1:
            continue
        if not all(match_company(winner, item.company).accepted for item in owners):
            continue
        for candidate in candidates:
            if (
                match_company(winner, candidate.company).accepted
                or text_key(candidate.company.company_name) != text_key(brand[0] if brand else "")
                or set(company_key(candidate.company.company_name).split()) & {"as", "ltd"}
                or not address_supports_identity(winner.address, candidate.company.address)
                or not all(
                    address_supports_identity(owner.company.address, candidate.company.address)
                    for owner in owners
                )
            ):
                continue
            owner = owners[0]
            bound = candidate.company.model_copy(
                update={"company_name": owner.company.company_name}
            )
            if not match_company(owner.company, bound).accepted:
                continue
            linked.append(
                CompanyCandidate(
                    company=bound,
                    evidence=[
                        *[
                            proof
                            for proof in candidate.evidence
                            if proof.field != CompanyField.COMPANY_NAME
                        ],
                        *[
                            proof
                            for proof in owner.evidence
                            if proof.field == CompanyField.COMPANY_NAME
                        ],
                    ],
                )
            )
    return linked


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
            result.issues.extend(search_issues(self.search, "enrichment"))
        pending = deque(dict.fromkeys(urls))
        visited: set[str] = set()
        followed: Counter[str] = Counter()
        identity_hosts: dict[str, str] = {}
        pages: list[tuple[Source, str, list[CompanyCandidate]]] = []
        while pending and len(visited) < self.settings.max_pages_per_tender:
            url = pending.popleft()
            if url in visited:
                continue
            visited.add(url)
            try:
                document = self.fetcher.fetch(url)
                if url in identity_hosts and domain(document.final_url) != identity_hosts[url]:
                    result.issues.append(
                        Issue(
                            stage="enrichment",
                            code="identity_redirect_offsite",
                            provider=self.name,
                            message="Company identity link redirected to another host; skipped.",
                        )
                    )
                    continue
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
                pages.append((source, document.body, candidates))
                result.candidates.extend(candidates)
                if source.source_type == SourceType.COMPANY_WEBSITE and not any(
                    match_company(winner, item.company).accepted for item in candidates
                ):
                    host = domain(document.final_url)
                    extra = [
                        link
                        for link in identity_links(document.body, document.final_url)
                        if link not in visited and link not in pending
                    ][: max(0, 2 - followed[host])]
                    followed[host] += len(extra)
                    identity_hosts.update((link, host) for link in extra)
                    pending.extendleft(reversed(extra))
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
                if isinstance(error, CollectionError) and error.code == "page_budget_exceeded":
                    break
        bound = link_contact_identity(pages, winner)
        result.candidates.extend(bound)
        if bound:
            result.issues.append(
                Issue(
                    stage="matching",
                    code="linked_company_identity",
                    provider=self.name,
                    message=(
                        "İletişim sayfası, bağlı künye/KVKK unvanı ve aynı posta adresiyle "
                        "eşleştirildi; kaynak kanıtları korundu."
                    ),
                )
            )
        return result
