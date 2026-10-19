"""Conservative Turkish normalization; identifiers remain strings."""

import re
import unicodedata
from urllib.parse import urlsplit

from tender_enricher.models import NormalizedTender, TenderInput


def text_key(value: str | None) -> str:
    value = (value or "").translate(str.maketrans("İI", "iı")).lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.translate(str.maketrans("ışğç", "isgc"))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def company_key(value: str | None) -> str:
    value = text_key(value)
    substitutions = {
        r"\banonim sirketi\b": "as",
        r"\ba s\b": "as",
        r"\blimited sirketi\b": "ltd",
        r"\bltd sti\b": "ltd",
        r"\bsanayi\b": "san",
        r"\bticaret\b": "tic",
    }
    for pattern, replacement in substitutions.items():
        value = re.sub(pattern, replacement, value)
    return value


def domain(value: str | None) -> str:
    if not value:
        return ""
    return (urlsplit(value).hostname or "").lower().removeprefix("www.")


def tender_id(value: str) -> str:
    match = re.fullmatch(r"\s*(\d{4})\s*/\s*(\d+)\s*", value)
    if not match or int(match[2]) == 0:
        raise ValueError("tender_id must use YYYY/number format")
    return f"{match[1]}/{int(match[2])}"


def normalize_tender(record: TenderInput) -> NormalizedTender:
    data = record.model_dump()
    data["tender_id"] = tender_id(record.tender_id)
    for field in ("title", "authority", "location"):
        if data[field]:
            data[field] = " ".join(data[field].split())
    return NormalizedTender.model_validate(data)


def normalize_value(field: str, value: str) -> str:
    if field in {"company_name", "winner.company_name"}:
        return company_key(value)
    if field == "website":
        return domain(value)
    if field == "email":
        return value.lower().removeprefix("mailto:").strip()
    if field == "phone":
        digits = re.sub(r"\D", "", value)
        if len(digits) == 11 and digits.startswith("0"):
            return "+90" + digits[1:]
        if len(digits) == 12 and digits.startswith("90"):
            return "+" + digits
        return digits
    if field in {"mersis_no", "tax_no"}:
        return re.sub(r"\D", "", value)
    return text_key(value)
