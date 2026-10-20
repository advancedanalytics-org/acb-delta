"""Rule-based atomic obligation extraction (design section 05).

One clause can hold several propositions; each gets subject / action / object / modality /
condition / deadline / exception and a span inside the clause text. Points (a, b, c…) under a
lead-in such as "Bên kiểm soát dữ liệu có trách nhiệm sau đây:" inherit its subject and modality.
"""

import re
from dataclasses import dataclass

from app.ria.textutil import extract_quantities, syllables

# Order matters: "không được" before "được phép", "không phải" before "phải".
MODALITY_MARKERS: list[tuple[str, str]] = [
    ("must_not", "không được phép"),
    ("must_not", "không được"),
    ("must_not", "nghiêm cấm"),
    ("must_not", "bị cấm"),
    ("may", "không phải"),  # exemption: "không phải thực hiện"
    ("may", "không bắt buộc"),
    ("must", "có trách nhiệm"),
    ("must", "chịu trách nhiệm"),
    ("must", "có nghĩa vụ"),
    ("must", "bắt buộc"),
    ("must", "phải"),
    ("may", "có quyền"),
    ("may", "được quyền"),
    ("may", "được phép"),
    ("may", "có thể"),
]
_MARKER_RE = re.compile(
    "|".join(rf"(?<![0-9a-zà-ỹđ]){re.escape(m)}(?![0-9a-zà-ỹđ])" for _, m in MODALITY_MARKERS),
    re.IGNORECASE,
)
_MODALITY_OF = {marker: modality for modality, marker in MODALITY_MARKERS}

_CONDITION_RE = re.compile(
    r"(?:trong trường hợp|trường hợp|trước khi|sau khi|khi|nếu)\s[^,;.:]+", re.IGNORECASE
)
_EXCEPTION_RE = re.compile(r"(?:trừ trường hợp|trừ khi|ngoại trừ)\s[^;.]+", re.IGNORECASE)
_SENTENCE_RE = re.compile(r"[^.;]+(?:[.;]|$)")
# "Chính phủ quy định chi tiết khoản này" delegates rule-making; it binds no regulated entity.
_DELEGATION_RE = re.compile(
    r"^(Chính phủ|Thủ tướng Chính phủ|Bộ trưởng[^,;.]*|Thống đốc[^,;.]*|Ngân hàng Nhà nước)\s+"
    r"(quy định|hướng dẫn)",
)

# Clauses that define terms or scope do not create obligations.
SKIP_ARTICLE_HEADINGS = ("giải thích từ ngữ", "phạm vi điều chỉnh", "đối tượng áp dụng")


class _Span:
    """Minimal match-like wrapper for a trimmed regex match."""

    def __init__(self, text: str) -> None:
        self._text = text

    def group(self, _: int = 0) -> str:
        return self._text


@dataclass
class Obligation:
    subject: str
    action: str
    object: str
    modality: str
    condition: str | None
    deadline: str | None
    exception: str | None
    text: str
    span_start: int
    span_end: int


@dataclass
class ClauseInput:
    numbering: str
    level: str
    text: str
    parent: str | None
    heading: str | None = None


def _clip_words(text: str, max_words: int, from_end: bool = False) -> str:
    words = text.split()
    words = words[-max_words:] if from_end else words[:max_words]
    return " ".join(words).strip(" ,:;-–")


def find_modality(text: str) -> tuple[str, re.Match] | None:
    m = _MARKER_RE.search(text)
    if not m:
        return None
    return _MODALITY_OF[m.group(0).lower()], m


def _analyse(
    sentence: str, inherited: tuple[str, str] | None, inherit_modality: bool
) -> dict | None:
    if _DELEGATION_RE.match(sentence):
        return None
    found = find_modality(sentence)
    if found:
        modality, m = found
        subject = _clip_words(sentence[: m.start()], 20, from_end=True)
        rest = sentence[m.end() :]
        if not subject and inherited:
            subject = inherited[1]
    elif inherited and inherit_modality:
        modality, subject = inherited
        rest = sentence
    else:
        return None

    rest = re.sub(r"^\s*(sau đây|như sau)?\s*:?\s*", "", rest)
    rest_words = syllables(rest)
    action = " ".join(rest_words[:2])
    condition = _CONDITION_RE.search(sentence)
    if condition and (cut := _MARKER_RE.search(condition.group(0))):
        # "X khi làm Y phải ..." — the condition stops at the modality marker.
        condition = _Span(condition.group(0)[: cut.start()])
    exception = _EXCEPTION_RE.search(sentence)
    obj = rest
    for cut in (condition, exception):
        if cut:
            obj = obj.replace(cut.group(0), " ")
    obj = _clip_words(" ".join(obj.split()[2:]), 30)
    quantities = extract_quantities(sentence)
    return {
        "subject": subject,
        "action": action,
        "object": obj,
        "modality": modality,
        "condition": condition.group(0).strip() if condition else None,
        "exception": exception.group(0).strip() if exception else None,
        "deadline": "; ".join(q.text.strip() for q in quantities) or None,
    }


def extract_obligations(clauses: list[ClauseInput]) -> dict[str, list[Obligation]]:
    """Return obligations keyed by clause numbering."""
    by_numbering = {c.numbering: c for c in clauses}
    children: dict[str, int] = {}
    for c in clauses:
        if c.parent:
            children[c.parent] = children.get(c.parent, 0) + 1

    def article_of(clause: ClauseInput) -> ClauseInput | None:
        node: ClauseInput | None = clause
        while node and node.level != "article":
            node = by_numbering.get(node.parent) if node.parent else None
        return node

    def lead_in(clause: ClauseInput) -> tuple[str, str] | None:
        """Modality + subject from a parent lead-in ("... có trách nhiệm sau đây:") or from an
        article heading such as "Trách nhiệm của bên kiểm soát dữ liệu"."""
        parent = by_numbering.get(clause.parent) if clause.parent else None
        if not parent or parent.level not in ("clause", "point", "article"):
            return None
        body = _body(parent).rstrip()
        if body.endswith(":"):
            found = find_modality(body)
            if found:
                modality, m = found
                return modality, _clip_words(body[: m.start()], 20, from_end=True)
            if named := _named_duty(body):
                return named
        if parent.level == "article" and (named := _named_duty(parent.heading or "")):
            return named
        return lead_in(parent)

    result: dict[str, list[Obligation]] = {}
    for clause in clauses:
        if clause.level not in ("article", "clause", "point"):
            continue
        article = article_of(clause)
        if article and (article.heading or "").lower().startswith(SKIP_ARTICLE_HEADINGS):
            continue
        body = _body(clause)
        offset = len(clause.text) - len(body)
        flat = body.replace("\n", " ")
        # A lead-in with children is carried by the children, not extracted on its own.
        if flat.rstrip().endswith(":") and children.get(clause.numbering):
            continue
        inherited = lead_in(clause)
        # Modality comes from the lead-in only when the clause states none itself.
        inherit_modality = find_modality(flat) is None
        found = []
        for m in _SENTENCE_RE.finditer(flat):
            sentence = m.group(0)
            stripped = sentence.strip()
            if len(syllables(stripped)) < 4:
                continue
            fields = _analyse(stripped, inherited, inherit_modality)
            if not fields:
                continue
            start = offset + m.start() + (len(sentence) - len(sentence.lstrip()))
            end = start + len(stripped)
            found.append(
                Obligation(text=clause.text[start:end], span_start=start, span_end=end, **fields)
            )
        if found:
            result[clause.numbering] = found
    return result


_NAMED_DUTY_RE = re.compile(
    r"^(nghĩa vụ|trách nhiệm|quyền)(?: và (?:nghĩa vụ|trách nhiệm|quyền))* của\s+(.+?)"
    r"(?:\s+bao gồm|\s+như sau|\s+sau đây|:|$)",
    re.IGNORECASE,
)


def _named_duty(text: str) -> tuple[str, str] | None:
    """'Nghĩa vụ của X bao gồm:' → (must, X); 'Quyền của X:' → (may, X)."""
    m = _NAMED_DUTY_RE.match(text.strip())
    if not m:
        return None
    kind = m.group(1).lower()
    modality = "may" if kind == "quyền" and " và " not in m.group(0).lower() else "must"
    return modality, _clip_words(m.group(2), 15)


# "a) ", "đ) ", "2. ", "3.1. " opening a point/clause: numbering, not words of the sentence.
_LABEL_RE = re.compile(r"^\s*(?:[a-zđ]|\d+(?:\.\d+)*)[).]\s+")


def _body(clause: ClauseInput) -> str:
    """Article text minus its heading line; clause/point text minus its label."""
    if clause.level == "article" and clause.heading and clause.text.startswith(clause.heading):
        return clause.text[len(clause.heading) :].lstrip("\n ")
    if clause.level in ("clause", "point"):
        return _LABEL_RE.sub("", clause.text, count=1)
    return clause.text
