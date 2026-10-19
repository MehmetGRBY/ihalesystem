"""Pure parsing helpers for a deliberately bounded HTML format."""

import json
import re
from collections.abc import Iterator
from typing import Any

from bs4 import BeautifulSoup, Tag
from pydantic import ValidationError

from tender_enricher.evidence import make_evidence
from tender_enricher.models import CompanyField, CompanyProfile, Evidence, Source
from tender_enricher.normalization import normalize_value, text_key

LABELS = {
    "tender_id": ["İhale Kayıt Numarası", "İhale Numarası", "İKN"],
    "winner": ["İhaleyi Kazanan", "Kazanan Firma", "Yüklenici", "Yüklenici Firma"],
    "company_name": ["Ticaret Unvanı", "Ticari Unvan", "Firma Unvanı", "Firma Adı"],
    "phone": ["Telefon", "Tel"],
    "email": ["E-posta", "Email", "Eposta"],
    "website": ["Web Sitesi", "Website", "İnternet Adresi", "Yüklenici Web Sitesi"],
    "address": ["Adres", "Açık Adres", "Yüklenici Adresi"],
    "city": ["Firma İli", "İl", "Şehir", "Yüklenici İli"],
    "district": ["Firma İlçesi", "İlçe"],
    "mersis_no": ["MERSİS No", "MERSİS Numarası"],
    "trade_registry_no": ["Ticaret Sicil No", "Ticaret Sicil Numarası"],
    "trade_registry_office": ["Ticaret Sicil Müdürlüğü"],
    "tax_no": ["Vergi No", "Vergi Numarası"],
    "tax_office": ["Vergi Dairesi"],
}
_lookup = {text_key(label): field for field, labels in LABELS.items() for label in labels}


def labeled_values(soup: BeautifulSoup) -> dict[str, list[tuple[str, str]]]:
    values: dict[str, list[tuple[str, str]]] = {}

    def add(label: str, value: str, locator: str) -> None:
        key = _lookup.get(text_key(label.rstrip(":")))
        if key and value.strip():
            values.setdefault(key, []).append((value.strip(), locator))

    for index, row in enumerate(soup.select("tr")):
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) == 2:
            add(
                cells[0].get_text(" ", strip=True),
                cells[1].get_text(" ", strip=True),
                f"tr[{index + 1}]",
            )
    for index, label in enumerate(soup.select("dt")):
        sibling = label.find_next_sibling("dd")
        if sibling:
            add(
                label.get_text(" ", strip=True),
                sibling.get_text(" ", strip=True),
                f"dt[{index + 1}]+dd",
            )
    for index, paragraph in enumerate(soup.select("p, li")):
        content = paragraph.get_text(" ", strip=True)
        if ":" in content:
            label_text, value = content.split(":", 1)
            add(label_text, value, f"p,li[{index + 1}]")
    return values


def cleaned_value(field: str, value: str) -> str | None:
    value = " ".join(value.split()).strip()
    if text_key(value) in {"", "yok", "bilinmiyor", "null", "none", "n a", "belirtilmemis"}:
        return None
    if field == "phone":
        normalized = normalize_value(field, value)
        if re.fullmatch(r"\+90\d{10}", normalized):
            return normalized
        return value if re.fullmatch(r"\+\d[\d ()-]{7,20}", value) else None
    if field == "email":
        normalized = normalize_value(field, value)
        return normalized if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", normalized) else None
    if field in {"mersis_no", "tax_no"}:
        value = re.sub(r"[\s-]", "", value)
    try:
        CompanyProfile.model_validate({field: value})
    except ValidationError:
        return None
    return value


def profile_from_values(
    values: dict[str, tuple[str, str]], source: Source
) -> tuple[CompanyProfile, list[Evidence]]:
    fields: dict[str, str] = {}
    evidence: list[Evidence] = []
    for field, (raw_value, locator) in values.items():
        if field not in CompanyProfile.model_fields:
            continue
        value = cleaned_value(field, raw_value)
        if value is None:
            continue
        if field == "website":
            value = str(CompanyProfile.model_validate({field: value}).website)
        fields[field] = value
        evidence.append(make_evidence(CompanyField(field), value, source, locator, raw_value))
    return CompanyProfile.model_validate(fields), evidence


def organizations(soup: BeautifulSoup) -> Iterator[tuple[dict[str, Any], str]]:
    def walk(node: Any, locator: str) -> Iterator[tuple[dict[str, Any], str]]:
        if isinstance(node, list):
            for index, value in enumerate(node):
                yield from walk(value, f"{locator}[{index}]")
        elif isinstance(node, dict):
            types = node.get("@type", [])
            types = [types] if isinstance(types, str) else types
            if isinstance(types, list) and any(
                item in {"Organization", "Corporation", "LocalBusiness", "GeneralContractor"}
                for item in types
                if isinstance(item, str)
            ):
                yield node, locator
            if "@graph" in node:
                yield from walk(node["@graph"], locator + ".@graph")

    for index, script in enumerate(soup.select('script[type="application/ld+json"]')):
        if not isinstance(script, Tag):
            continue
        try:
            yield from walk(json.loads(script.get_text()), f"jsonld[{index}]")
        except (ValueError, TypeError):
            continue


def organization_values(node: dict[str, Any], locator: str) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for field, key in {
        "company_name": "legalName",
        "phone": "telephone",
        "email": "email",
        "website": "url",
        "tax_no": "taxID",
    }.items():
        value = node.get(key) or (node.get("name") if field == "company_name" else None)
        if isinstance(value, str):
            result[field] = (value, locator + "." + key)
    address = node.get("address")
    if isinstance(address, str):
        result["address"] = (address, locator + ".address")
    elif isinstance(address, dict):
        parts = [
            address.get(key)
            for key in ("streetAddress", "addressLocality", "addressRegion", "postalCode")
        ]
        if isinstance(address.get("streetAddress"), str):
            result["address"] = (
                ", ".join(part for part in parts if isinstance(part, str)),
                locator + ".address",
            )
        region, locality = address.get("addressRegion"), address.get("addressLocality")
        if isinstance(region, str):
            result["city"] = (region, locator + ".address.addressRegion")
            if isinstance(locality, str):
                result["district"] = (locality, locator + ".address.addressLocality")
    identifiers = node.get("identifier", [])
    if isinstance(identifiers, dict):
        identifiers = [identifiers]
    if isinstance(identifiers, list):
        for index, identifier in enumerate(identifiers):
            if isinstance(identifier, dict):
                name = text_key(str(identifier.get("propertyID", identifier.get("name", ""))))
                identifier_field = {"mersis": "mersis_no", "mersis no": "mersis_no"}.get(name)
                value = identifier.get("value")
                if identifier_field and isinstance(value, str):
                    result[identifier_field] = (value, f"{locator}.identifier[{index}]")
    return result
