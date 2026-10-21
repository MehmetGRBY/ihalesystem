"""Conservative EFA fit: explicit work scope, never a generic building assumption."""

import re

from source_adapters import normalize

LABELS = {
    "klima": "Klima / iklimlendirme",
    "havalandirma": "Havalandırma",
    "isitma": "Isıtma",
    "sogutma": "Soğutma",
    "mekanik": "Mekanik tesisat",
}
PATTERNS = {
    "klima": r"\b(?:klima\w*|iklimlendirme\w*|vrf|vrv|hvac|isi pompasi\w*|fan\s*coil\w*|fancoil\w*)\b",
    "havalandirma": r"\b(?:havalandirma\w*|havalandirilma\w*|hava (?:isleme|hazirlama) santrali\w*)\b",
    "isitma": r"\b(?:isitma\w*|kalorifer\w*|boyler\w*|kombi\w*|radyant\w*|kazan dairesi\w*|(?:yogusmali|kalorifer|isitma|sicak su|buhar) kazan\w*|kazan (?:alimi|degisimi|donusumu|bakimi|onarimi|montaji)|dogal\s*gaz (?:tesisati\w*|donusum\w*))\b",
    "sogutma": r"\b(?:sogutma\w*|chiller\w*|kondenser\w*|kondanser\w*|konderser\w*|soguk hava (?:deposu|depolari)\w*)\b",
    "mekanik": r"\bmekanik tesisat\w*\b",
}
# Mask misleading uses without rejecting an independent HVAC item in a mixed tender.
FALSE_USES = [
    r"\b(?:kok|cim|toprak) havalandirma\w*(?: makine\w*)?",
    r"\b(?:klimali|iklimlendirmeli) (?:arac\w*|otobus\w*|tasit\w*)",
    r"\bsut (?:tasima ve sut )?sogutma\w*(?: tank\w*)?",
    r"\byangin sondurme ve sogutma\w*",
    r"\b(?:yemek|cay|corba|pisirme) kazan\w*",
]
FUEL = re.compile(
    r"\b(?:komur\w*|odun\w*|pelet\w*|motorin\w*|akaryakit\w*|fuel oil|mazot\w*|kati yakit\w*)\b"
)
TECHNICAL_WORK = re.compile(
    r"\b(?:montaj\w*|kurulum\w*|onarim\w*|revizyon\w*|donusum\w*|yenilen\w*|degisim\w*|bakim(?:i|lari|larinin)? (?:onarim\w*|hizmet\w*|isi))\b"
)
LABOR = re.compile(r"\b(?:yardimci iscilik|personel calistirilmasi|personel temini)\b")


VEHICLE_WORK = re.compile(r"\b(?:oto elektrik|otobus\w*|metrobus\w*|arac yangin\w*|buji|cng)\b")
FACILITY = re.compile(r"\b(?:bina\w*|atolye\w*|lojman\w*|yerleske\w*|hastane\w*|okul\w*)\b")


def match_work(text, *, context=""):
    """Return category keys only for the stated work, excluding common false positives."""
    value = normalize(text or "")
    whole = normalize(context or "") + " " + value
    if VEHICLE_WORK.search(whole) and not FACILITY.search(whole):
        return []
    if FUEL.search(whole) and not TECHNICAL_WORK.search(whole):
        return []
    if LABOR.search(whole) and not TECHNICAL_WORK.search(whole):
        return []
    for pattern in FALSE_USES:
        value = re.sub(pattern, " ", value)
    return [key for key, pattern in PATTERNS.items() if re.search(pattern, value)]


def scope_fields(text):
    """Read the work description; qualification, contact and similar-work sections do not count."""
    text = text or ""
    patterns = [
        r"3\.2\.\s*Niteliği[^:]*:\s*(.*?)\s*3\.3\.",
        r"2\s*[-–]\s*İhale konusu.{0,150}?b\)\s*(?:Niteliği|Niteliği, türü ve miktarı)[^:]*:\s*(.*?)\s*c\)",
    ]
    return [
        " ".join(match.group(1).split())
        for pattern in patterns
        for match in re.finditer(pattern, text, re.I | re.S)
    ]


def assess(row):
    if row.get("is_demo"):
        return {
            "matched": True,
            "categories": ["mekanik"],
            "basis": "demo",
            "evidence": "Sentetik demo kaydı; gerçek ihale değildir.",
            "policy_version": 1,
        }
    candidates = [("title", row.get("title") or "")]
    if row.get("match_evidence") and row.get("match_basis") in ("title", "scope"):
        candidates.append((row["match_basis"], row["match_evidence"]))
    candidates.extend(("scope", value) for value in scope_fields(row.get("announcement_text")))
    for event in row.get("related_announcements") or []:
        candidates.append(("title", event.get("title") or ""))
        candidates.extend(
            ("scope", value) for value in scope_fields(event.get("announcement_text"))
        )
    found = []
    seen = set()
    for basis, text in candidates:
        if not text or (basis, text) in seen:
            continue
        seen.add((basis, text))
        categories = match_work(text, context=row.get("title"))
        if categories:
            found.append((basis, text, categories))
    if not found:
        return {
            "matched": False,
            "categories": [],
            "basis": None,
            "evidence": None,
            "policy_version": 1,
        }
    # Prefer the description to a title when both provide explicit evidence.
    basis, evidence, _ = next((entry for entry in found if entry[0] == "scope"), found[0])
    categories = [key for key in LABELS if any(key in entry[2] for entry in found)]
    return {
        "matched": True,
        "categories": categories,
        "basis": basis,
        "evidence": evidence[:1200],
        "policy_version": 1,
    }
