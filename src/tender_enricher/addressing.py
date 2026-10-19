"""Compare explicit postal addresses without treating a city or street as identity."""

import re
from dataclasses import dataclass

from tender_enricher.normalization import text_key


@dataclass(frozen=True)
class PostalIdentity:
    street: str
    kind: str
    number: str
    district: str
    city: str
    quarter: str
    unit: str
    block: str
    floor: str


def postal_identity(value: str) -> PostalIdentity | None:
    # Preserve slashes in house/office numbers and explicitly printed district/city.
    text = " / ".join(text_key(part) for part in value.split("/"))
    location = re.search(r"\b([a-z]+)\s*/\s*([a-z]+)\s*$", text)
    streets = list(re.finditer(r"\b(sk|sok|sokak|sokagi|cd|cad|cadde|caddesi)\b", text))
    numbers = [
        item
        for item in re.finditer(r"\bno\s+(\d+[a-z]?(?:\s*/\s*\d+[a-z]?)?)\b", text)
        if not re.search(r"\b(?:ic kapi|daire|kapi)\s*$", text[: item.start()])
    ]
    if not location or len(streets) != 1 or len(numbers) != 1:
        return None
    street = streets[0]
    prefix = text[: street.start()].strip()
    quarters = re.split(r"\b(?:mah|mh|mahalle|mahallesi)\b", prefix)
    if len(quarters) > 2:
        return None
    name = quarters[-1].strip()
    if not 1 <= len(name.split()) <= 5 or re.search(r"\b(?:no|blok|kat)\b", name):
        return None
    unit = re.search(r"\b(?:ic kapi|daire|kapi)\s+(?:no\s+)?([a-z0-9]+)\b", text)
    block = re.search(r"\b([a-z0-9]+)\s+blok\b", text)
    floor = re.search(r"\bkat\s+([a-z0-9]+)\b", text)
    return PostalIdentity(
        street=name,
        kind="street" if street[1] in {"sk", "sok", "sokak", "sokagi"} else "avenue",
        number=re.sub(r"\s+", "", numbers[0][1]),
        district=location[1],
        city=location[2],
        quarter=quarters[0].strip() if len(quarters) == 2 else "",
        unit=unit[1] if unit else "",
        block=block[1] if block else "",
        floor=floor[1] if floor else "",
    )


def same_address(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    if re.search(r"[-−]\s*\d", left + right) and left.casefold() != right.casefold():
        return False
    if text_key(left) == text_key(right):
        return True
    a, b = postal_identity(left), postal_identity(right)
    if a is None or b is None:
        return False
    if (a.street, a.kind, a.number, a.district, a.city, a.unit) != (
        b.street,
        b.kind,
        b.number,
        b.district,
        b.city,
        b.unit,
    ):
        return False
    # A missing optional qualifier never bridges two conflicting published qualifiers.
    return not any(
        x and y and x != y
        for x, y in ((a.quarter, b.quarter), (a.block, b.block), (a.floor, b.floor))
    )


def address_supports_identity(left: str | None, right: str | None) -> bool:
    if not same_address(left, right):
        return False
    return all(
        re.search(r"\d", key)
        and re.search(r"\b(?:no|cad|cd|caddesi|sk|sok|sokak|street|road|avenue)\b", key)
        for key in (text_key(left), text_key(right))
    )
