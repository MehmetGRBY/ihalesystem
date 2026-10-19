import hashlib
from urllib.parse import urlsplit
from uuid import uuid4

import tldextract
from pydantic import HttpUrl

from tender_enricher.models import CompanyField, Evidence, Source, SourceType, utc_now

_extract = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


def publisher_group(url: str) -> str:
    parsed = _extract(url)
    return parsed.top_domain_under_public_suffix or (urlsplit(url).hostname or "")


def make_source(
    url: str, final_url: str, body: str, kind: SourceType, *, is_demo: bool = False
) -> Source:
    return Source(
        id=str(uuid4()),
        url=HttpUrl(url),
        final_url=HttpUrl(final_url),
        source_type=kind,
        publisher_group=publisher_group(final_url),
        retrieved_at=utc_now(),
        content_sha256=hashlib.sha256(body.encode()).hexdigest(),
        is_demo=is_demo,
    )


def make_evidence(
    field: CompanyField, value: str, source: Source, locator: str, excerpt: str
) -> Evidence:
    return Evidence(
        field=field,
        value=value,
        source_id=source.id,
        locator=locator,
        excerpt=excerpt[:600],
    )
