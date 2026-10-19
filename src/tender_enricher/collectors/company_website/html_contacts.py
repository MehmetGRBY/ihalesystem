"""Read public contact markup; every identity and contact value needs a locator."""

import re
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup, Tag

from tender_enricher.collectors.parsing import cleaned_value, labeled_values, profile_from_values
from tender_enricher.evidence import publisher_group
from tender_enricher.models import CompanyCandidate, Source
from tender_enricher.normalization import company_key, text_key

Observations = dict[str, list[tuple[str, str]]]
ORG_TYPES = {"Organization", "Corporation", "LocalBusiness", "GeneralContractor"}
LABELS = {
    "adres": "address",
    "adresimiz": "address",
    "address": "address",
    "location": "address",
    "telefon": "phone",
    "phone": "phone",
    "tel": "phone",
    "bizi arayin": "phone",
    "e posta": "email",
    "eposta": "email",
    "email": "email",
    "e mail": "email",
}


def candidate(values: Observations, source: Source) -> CompanyCandidate | None:
    first_valid = {
        field: valid[0]
        for field, items in values.items()
        if (valid := [item for item in items if cleaned_value(field, item[0]) is not None])
    }
    profile, _ = profile_from_values(first_valid, source)
    if not profile.company_name:
        return None
    evidence = []
    for key, items in values.items():
        for value in items:
            _, extra = profile_from_values({key: value}, source)
            evidence.extend(extra)
    return CompanyCandidate(company=profile, evidence=evidence)


def node_value(node: Tag) -> str:
    return str(node.get("content") or node.get("href") or node.get_text(" ", strip=True))


def semantic_contacts(soup: BeautifulSoup, source: Source) -> list[CompanyCandidate]:
    results = []
    for index, scope in enumerate(soup.select("[itemscope][itemtype], .vcard")):
        kinds = {part.rsplit("/", 1)[-1] for part in str(scope.get("itemtype", "")).split()}
        if not (kinds & ORG_TYPES) and not (
            "vcard" in scope.get("class", []) and scope.select(".org")
        ):
            continue
        values: Observations = {}
        selectors = {
            "company_name": '[itemprop="legalName"], [itemprop="name"], .org, .fn',
            "phone": '[itemprop="telephone"], .tel',
            "email": '[itemprop="email"], .email',
            "website": '[itemprop="url"], .url',
            "address": '[itemprop="streetAddress"], .street-address',
            "city": '[itemprop="addressRegion"], .region',
            "district": '[itemprop="addressLocality"], .locality',
        }
        if scope.select('[itemprop="legalName"]'):
            selectors["company_name"] = '[itemprop="legalName"]'
        if scope.select('[itemprop="address"], .adr'):
            selectors["address"] = '[itemprop="address"], .adr'
        for field, selector in selectors.items():
            for child in scope.select(selector):
                # Do not attribute a nested subsidiary or person to its parent.
                parents = list(child.find_parents())
                parents = parents[: parents.index(scope)] if scope in parents else []
                if any(
                    str(parent.get("itemtype", "")).rsplit("/", 1)[-1] in ORG_TYPES | {"Person"}
                    or (field in {"company_name", "website"} and parent.has_attr("itemscope"))
                    for parent in parents
                ):
                    continue
                value = node_value(child)
                if field == "phone":
                    value = unquote(value).removeprefix("tel:")
                if field == "email":
                    value = unquote(value).removeprefix("mailto:").split("?", 1)[0].strip()
                values.setdefault(field, []).append(
                    (value, f"organization[{index + 1}] {selector}")
                )
        names = values.get("company_name", [])
        if len({company_key(value) for value, _ in names}) != 1:
            continue
        result = candidate(values, source)
        if result:
            results.append(result)
    return results


def site_identity(soup: BeautifulSoup) -> tuple[str, str] | None:
    meta = soup.select_one('meta[property="og:site_name"]')
    if meta and meta.get("content"):
        return str(meta["content"]).strip(), 'meta[property="og:site_name"]'
    for image in soup.select("header a img[alt]"):
        label = str(image.get("alt", "")).strip()
        if label and text_key(label) not in {"logo", "home", "anasayfa", "site logo"}:
            return label, "header a img[alt]"
    if soup.title:
        parts = re.split(r"\s+[|–—-]\s+", soup.title.get_text(" ", strip=True))
        generic = {
            "contact",
            "contact us",
            "contact details",
            "iletisim",
            "iletisim bilgileri",
            "iletisim formu",
            "home",
            "anasayfa",
            "hakkimizda",
        }
        for part in parts:
            if 2 <= len(part) <= 120 and text_key(part) not in generic:
                return part, "title"
    return None


def public_contacts(soup: BeautifulSoup, source: Source) -> list[CompanyCandidate]:
    semantic = semantic_contacts(soup, source)
    if semantic:
        return semantic
    identity = site_identity(soup)
    if identity is None:
        return []
    brand, locator = identity
    brand_tokens = text_key(brand).split()
    if not brand_tokens:
        return []
    legal_names: dict[str, tuple[str, str]] = {}
    legal = re.compile(
        r"\b(?:anonim\s+şirketi|limited\s+şirketi|a\s*\.\s*ş\s*\.|ltd\.?\s*şti\.?)", re.I
    )
    for index, paragraph in enumerate(soup.select("p, h1, h2, h3, address")):
        text = paragraph.get_text(" ", strip=True)
        if len(text) > 350 or not text_key(text).startswith(brand_tokens[0]):
            continue
        match = legal.search(text)
        if match:
            name = text[: match.end()]
            legal_names[company_key(name)] = (name, f"p,h1,h2,h3,address[{index + 1}]")
    if len(legal_names) > 1:
        return []
    if legal_names:
        brand, locator = next(iter(legal_names.values()))
    values: Observations = {"company_name": [(brand, locator)]}
    canonical = soup.select_one('link[rel="canonical"][href]')
    if canonical:
        url = str(canonical["href"])
        if (
            urlsplit(url).scheme in {"http", "https"}
            and publisher_group(url) == source.publisher_group
        ):
            values["website"] = [(url, 'link[rel="canonical"]')]
    for index, link in enumerate(soup.select('a[href^="tel:"], a[href^="mailto:"]')):
        field = "phone" if str(link["href"]).startswith("tel:") else "email"
        value = unquote(str(link["href"])).split(":", 1)[1].split("?", 1)[0].strip()
        values.setdefault(field, []).append((value, f"a[{field}][{index + 1}]"))
    for field, observations in labeled_values(soup).items():
        if field in {"phone", "email", "address"}:
            values.setdefault(field, []).extend(observations)
    for index, heading in enumerate(soup.select("h2, h3, h4, h5, h6, dt")):
        labeled_field = LABELS.get(text_key(heading.get_text(" ", strip=True)))
        if labeled_field:
            sibling = heading.find_next_sibling(["p", "div", "dd", "a"])
            if sibling:
                values.setdefault(labeled_field, []).append(
                    (sibling.get_text(" ", strip=True), f"contact-heading[{index + 1}]+value")
                )
    for index, node in enumerate(soup.select('address, [class*="footer"] p, a[href*="maps"]')):
        text = node.get_text(" ", strip=True)
        text = re.sub(r"^(?:adres|address|location)\s*:\s*", "", text, flags=re.I)
        if (
            len(text) <= 300
            and re.search(
                r"\b(?:mah\.?|mh\.?|mahallesi|cad\.?|cd\.?|caddesi|sok\.?|sk\.?|sokak)\s",
                text,
                re.I,
            )
            and re.search(r"\bno\s*[:.]?\s*\d", text, re.I)
        ):
            values.setdefault("address", []).append((text, f"address/footer/maps[{index + 1}]"))
    if not any(values.get(field) for field in ("phone", "email", "address")):
        return []
    result = candidate(values, source)
    return [result] if result else []
