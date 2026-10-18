"""Vietnamese text helpers shared by parsing, retrieval and comparison.

Vietnamese words are mostly two syllables, so syllable bigrams carry most of the meaning
("dữ liệu", "khách hàng"). Retrieval and lexical gating work on those bigrams.
"""

import re
import unicodedata
from dataclasses import dataclass

_WORD = re.compile(r"[0-9a-zà-ỹđ]+", re.IGNORECASE)

# Function words that never carry topic on their own.
STOP_SYLLABLES = frozenset(
    """và hoặc của các những cho với theo tại trong khi nếu thì là được bị có không này đó đã sẽ
    đang để từ về đến do bởi mà như một hai ba mỗi trên dưới sau trước nhằm vào ra lại cũng còn
    phải nào gì ai sự việc cái""".split()
)

# Legal boilerplate bigrams: frequent in every document, useless for matching topics.
STOP_BIGRAMS = frozenset(
    {
        "quy định",
        "theo quy",
        "định tại",
        "định của",
        "tại khoản",
        "tại điều",
        "khoản này",
        "điều này",
        "luật này",
        "nghị định",
        "định này",
        "thông tư",
        "tư này",
        "trường hợp",
        "pháp luật",
        "có liên",
        "liên quan",
        "cơ quan",
        "tổ chức",
        "thực hiện",
        "đối với",
        "bao gồm",
        "sau đây",
        "có thẩm",
        "thẩm quyền",
        "nhà nước",
        "trách nhiệm",
        "có trách",
        "kể từ",
        "từ ngày",
        "trừ trường",
        "chịu trách",
        "nghĩa vụ",
        "có nghĩa",
        "áp dụng",
        "thi hành",
        "hiệu lực",
        # Cross-word bigrams of boilerplate phrases ("hiệu lực thi hành", "Nghị định số").
        "lực thi",
        "định số",
        "hợp quy",
        "tắc quy",
    }
)


def normalize(text: str) -> str:
    """NFC + collapse whitespace. Keeps diacritics: they distinguish Vietnamese words."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def syllables(text: str) -> list[str]:
    return [m.group(0).lower() for m in _WORD.finditer(unicodedata.normalize("NFC", text))]


def content_bigrams(text: str) -> list[str]:
    """Adjacent syllable pairs without stop syllables or boilerplate, in order, deduplicated."""
    sylls = syllables(text)
    seen: dict[str, None] = {}
    for a, b in zip(sylls, sylls[1:], strict=False):
        if a in STOP_SYLLABLES or b in STOP_SYLLABLES or a.isdigit() or b.isdigit():
            continue
        bigram = f"{a} {b}"
        if bigram not in STOP_BIGRAMS:
            seen[bigram] = None
    return list(seen)


def content_unigrams(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for s in syllables(text):
        if s not in STOP_SYLLABLES and not s.isdigit() and len(s) > 1:
            seen[s] = None
    return list(seen)


def tsquery_from_bigrams(bigrams: list[str], limit: int = 40) -> str:
    """OR of phrase queries for Postgres full-text search with the 'simple' config."""
    parts = []
    for bigram in bigrams[:limit]:
        a, b = bigram.split(" ")
        parts.append(f"({a} <-> {b})")
    return " | ".join(parts)


# --- Quantities: deadlines, frequencies, ratios -------------------------------------------

_DIGITS = {
    "không": 0,
    "một": 1,
    "mốt": 1,
    "hai": 2,
    "ba": 3,
    "bốn": 4,
    "tư": 4,
    "năm": 5,
    "lăm": 5,
    "sáu": 6,
    "bảy": 7,
    "tám": 8,
    "chín": 9,
}
_NUMBER_WORDS = r"(?:không|một|mốt|hai|ba|bốn|tư|năm|lăm|sáu|bảy|tám|chín|mười|mươi|trăm|lẻ|linh)"

# Units ordered so the longest match wins ("ngày làm việc" before "ngày").
_UNITS = {
    "ngày làm việc": ("business_day", 1.0),
    "ngày": ("day", 1.0),
    "tuần": ("day", 7.0),
    "tháng": ("day", 30.0),
    "năm": ("day", 365.0),
    "giờ": ("hour", 1.0),
    "%": ("percent", 1.0),
    "phần trăm": ("percent", 1.0),
    "tỷ đồng": ("money", 1e9),
    "triệu đồng": ("money", 1e6),
    "nghìn đồng": ("money", 1e3),
    "ngàn đồng": ("money", 1e3),
    "đồng": ("money", 1.0),
    "VND": ("money", 1.0),
}
_UNIT_RE = "|".join(re.escape(u) for u in sorted(_UNITS, key=len, reverse=True))

_MAX_QUALIFIERS = ("tối đa", "không quá", "chậm nhất", "trong thời hạn", "trong vòng", "trong")
_MIN_QUALIFIERS = ("tối thiểu", "ít nhất", "không dưới", "không ít hơn")

_QUANTITY = re.compile(
    rf"(?P<qual>tối đa|không quá|chậm nhất|trong thời hạn|trong vòng|trong|tối thiểu|ít nhất|"
    rf"không dưới|không ít hơn|định kỳ)?\s*"
    rf"(?P<num>\d{{1,3}}(?:\.\d{{3}})+|\d+(?:[.,]\d+)?|{_NUMBER_WORDS}(?:\s+{_NUMBER_WORDS})*)\s*"
    rf"(?P<unit>{_UNIT_RE})(?![0-9a-zà-ỹđ])",
    re.IGNORECASE,
)


def parse_vietnamese_number(words: str) -> float | None:
    """Parse numbers like '12', '2,5', 'mười lăm', 'sáu mươi', 'ba mươi', 'một trăm'."""
    words = words.strip().lower()
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", words):  # Vietnamese thousands: 50.000
        return float(words.replace(".", ""))
    if re.fullmatch(r"\d+(?:[.,]\d+)?", words):
        return float(words.replace(",", "."))
    total, current = 0, 0
    tokens = words.split()
    if not tokens:
        return None
    for token in tokens:
        if token in _DIGITS:
            current += _DIGITS[token]
        elif token == "mười":
            current += 10
        elif token == "mươi":
            current = (current or 1) * 10
        elif token == "trăm":
            total += (current or 1) * 100
            current = 0
        elif token in ("lẻ", "linh"):
            continue
        else:
            return None
    return float(total + current)


@dataclass(frozen=True)
class Quantity:
    value: float  # in base units of `dimension`
    raw_value: float
    unit: str
    dimension: str  # day | business_day | hour | percent
    bound: str  # max | min | exact
    start: int
    end: int
    text: str


def extract_quantities(text: str) -> list[Quantity]:
    found = []
    for m in _QUANTITY.finditer(text):
        raw = parse_vietnamese_number(m.group("num"))
        if raw is None:
            continue
        unit = m.group("unit").lower()
        # Dates: "ngày 15 tháng 01 năm 2024" — a number right after the unit means a date part.
        if unit in ("tháng", "năm", "ngày") and re.match(r"\s*\d", text[m.end() :]):
            continue
        dimension, factor = _UNITS[unit]
        qual = (m.group("qual") or "").lower()
        bound = "max" if qual in _MAX_QUALIFIERS else "min" if qual in _MIN_QUALIFIERS else "exact"
        # Bound words belong to the value ("tối đa 12 tháng"); "định kỳ" does not.
        start = m.start("qual") if bound != "exact" else m.start("num")
        found.append(
            Quantity(
                value=raw * factor,
                raw_value=raw,
                unit=unit,
                dimension=dimension,
                bound=bound,
                start=start,
                end=m.end(),
                text=text[start : m.end()],
            )
        )
    return found
