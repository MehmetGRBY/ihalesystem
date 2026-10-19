from tender_enricher.collectors.company_website.website import CompanyWebsiteCollector
from tender_enricher.collectors.contracts import PageFetcher
from tender_enricher.config import Settings
from tender_enricher.models import Collection, CompanyProfile, NormalizedTender


class PublicRegistryCollector:
    """Public HTML supplied by URL; no registry login or assumed live portal support."""

    name = "public_registry"

    def __init__(self, fetcher: PageFetcher, settings: Settings) -> None:
        self.delegate = CompanyWebsiteCollector(fetcher, settings)

    def collect(self, tender: NormalizedTender, winner: CompanyProfile) -> Collection:
        registry_tender = tender.model_copy(update={"company_urls": tender.registry_urls})
        # Registry lookup must not re-fetch the corporate site.
        company = winner.model_copy(update={"website": None})
        return self.delegate.collect(registry_tender, company)
