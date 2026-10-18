"""NLP span detection for fine-grained differences (design section 11, RIA 4.0 06.3).

Two steps, both returning character offsets into the original strings:

1. Tag typed spans in a sentence. Words and parts of speech come from underthesea's Vietnamese
   CRF word segmenter / POS tagger (falls back to syllables when the model is unavailable). On top
   of them: ACTOR (noun phrase before the modal), ACTION (verb phrase after it), OBJECT (noun phrase
   after the action), plus lexicon/regex spans MODALITY, NEGATION, VALUE (durations, money, %),
   FREQUENCY, CONDITION and EXCEPTION.
2. Align the obligation with the closest sentence of the internal clause word by word
   (difflib) and report each replaced / inserted / deleted region with the span types it touches.

The result feeds the rule checks (scope differences), the LLM judge (as hints) and Engine 3, which
needs the exact target span to patch.
"""

import logging
import re
import threading
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher

from app.ria.obligations import _CONDITION_RE, _EXCEPTION_RE, _MARKER_RE
from app.ria.textutil import extract_quantities

log = logging.getLogger(__name__)

_NEGATION_RE = re.compile(
    r"(?<![0-9a-zà-ỹđ])(không|chưa|chẳng|cấm|nghiêm cấm)(?![0-9a-zà-ỹđ])", re.IGNORECASE
)
_FREQUENCY_RE = re.compile(
    r"(định kỳ|hằng|hàng)\s+(ngày|tuần|tháng|quý|năm)|định kỳ|mỗi\s+\S+(\s+\S+)?\s+một lần",
    re.IGNORECASE,
)
_SENTENCE_RE = re.compile(r"[^.;\n]+[.;]?")
_SYLLABLE_RE = re.compile(r"[0-9a-zà-ỹđ%]+(?:[.,][0-9]+)*", re.IGNORECASE)

# Spans whose difference changes what the rule means (scope), as opposed to its wording.
SCOPE_TYPES = ("ACTOR", "OBJECT", "CONDITION", "EXCEPTION")

_pos_lock = threading.Lock()
_pos_state: dict = {}


@dataclass
class Token:
    text: str
    norm: str
    start: int
    end: int
    pos: str | None


@dataclass
class Span:
    type: str
    start: int
    end: int
    text: str


def nlp_backend() -> str:
    _pos_tagger()
    return "underthesea" if _pos_state.get("fn") else "syllable"


def _pos_tagger():
    """underthesea.pos_tag, loaded once. CRF tagging is not documented as thread-safe: lock it."""
    if "fn" not in _pos_state:
        with _pos_lock:
            if "fn" not in _pos_state:
                try:
                    from underthesea import pos_tag

                    _pos_state["fn"] = pos_tag
                except Exception as exc:  # model missing: degrade to syllables
                    log.warning("underthesea unavailable (%s); syllable tokens only", exc)
                    _pos_state["fn"] = None
    return _pos_state["fn"]


def tokens(text: str) -> list[Token]:
    """Words with POS tags and offsets into `text`."""
    tagger = _pos_tagger()
    if tagger is None:
        return [
            Token(m.group(0), m.group(0).lower(), m.start(), m.end(), None)
            for m in _SYLLABLE_RE.finditer(text)
        ]
    with _pos_lock:
        tagged = tagger(text)
    out, cursor = [], 0
    for word, pos in tagged:
        idx = text.find(word, cursor)
        if idx < 0:  # tokenizer normalised the word; skip rather than guess its offset
            continue
        cursor = idx + len(word)
        if re.search(r"\w", word):
            out.append(Token(word, word.lower(), idx, cursor, pos))
    return out


def _phrase(toks: list[Token], i: int, tags: tuple[str, ...], step: int) -> tuple[int, int] | None:
    """Maximal run of tokens with a POS in `tags`, from index i walking by step (±1)."""
    j = i
    while 0 <= j < len(toks) and (toks[j].pos or "N")[:1] in tags:
        j += step
    if j == i:
        return None
    lo, hi = (i, j - 1) if step > 0 else (j + 1, i)
    return toks[lo].start, toks[hi].end


def tag_spans(text: str, toks: list[Token] | None = None) -> list[Span]:
    toks = toks if toks is not None else tokens(text)
    spans: list[Span] = []

    def add(kind: str, start: int, end: int) -> None:
        if end > start:
            spans.append(Span(kind, start, end, text[start:end]))

    modal = _MARKER_RE.search(text)
    if modal:
        add("MODALITY", modal.start(), modal.end())
        split_start, split_end = modal.start(), modal.end()
    else:
        # No modal ("Đơn vị thực hiện rà soát…"): the first verb starts the predicate.
        verb = next((t for t in toks if (t.pos or "")[:1] == "V"), None)
        split_start = split_end = verb.start if verb else None
    if split_start is not None:
        before = [t for t in toks if t.end <= split_start]
        after = [i for i, t in enumerate(toks) if t.start >= split_end]
        if before:
            actor = _phrase(toks, toks.index(before[-1]), ("N", "Np", "Nc", "M"), -1)
            if actor:
                add("ACTOR", *actor)
        if after:
            action = _phrase(toks, after[0], ("V",), 1)
            if action:
                add("ACTION", *action)
                nxt = next((i for i, t in enumerate(toks) if t.start >= action[1]), None)
                obj = _phrase(toks, nxt, ("N", "Np", "Nc"), 1) if nxt is not None else None
                if obj:
                    add("OBJECT", *obj)
    for m in _NEGATION_RE.finditer(text):
        if not (modal and modal.start() <= m.start() < modal.end()):
            add("NEGATION", m.start(), m.end())
    for q in extract_quantities(text):
        add("VALUE", q.start, q.end)
    for m in _FREQUENCY_RE.finditer(text):
        add("FREQUENCY", m.start(), m.end())
    for regex, kind in ((_CONDITION_RE, "CONDITION"), (_EXCEPTION_RE, "EXCEPTION")):
        for m in regex.finditer(text):
            add(kind, m.start(), m.end())
    return sorted(spans, key=lambda s: (s.start, s.end))


def _overlapping(spans: list[Span], start: int, end: int) -> list[Span]:
    if start == end:  # insertion point: the span that contains it
        return [s for s in spans if s.start < start < s.end]
    return [s for s in spans if s.start < end and start < s.end]


def best_sentence(source: str, target: str) -> tuple[int, int, float]:
    """Sentence of `target` most similar to `source` (word overlap ratio), with its offsets."""
    src = [t.norm for t in tokens(source)]
    best = (0, len(target), -1.0)
    for m in _SENTENCE_RE.finditer(target):
        sentence = m.group(0)
        if not sentence.strip():
            continue
        tgt = [t.norm for t in tokens(sentence)]
        ratio = SequenceMatcher(None, src, tgt, autojunk=False).ratio()
        if ratio > best[2]:
            lead = len(sentence) - len(sentence.lstrip())
            best = (m.start() + lead, m.start() + len(sentence.rstrip()), ratio)
    return best


def span_diff(source: str, target: str) -> dict:
    """Typed word-level differences between an obligation and an internal clause.

    Offsets in "source" refer to `source`; offsets in "target" refer to the whole `target`.
    """
    t_start, t_end, _ = best_sentence(source, target)
    src_text, tgt_text = source, target[t_start:t_end]
    src_tok, tgt_tok = tokens(src_text), tokens(tgt_text)
    src_spans, tgt_spans = tag_spans(src_text, src_tok), tag_spans(tgt_text, tgt_tok)
    matcher = SequenceMatcher(
        None, [t.norm for t in src_tok], [t.norm for t in tgt_tok], autojunk=False
    )

    def region(toks: list[Token], lo: int, hi: int) -> tuple[int, int]:
        if lo < hi:
            return toks[lo].start, toks[hi - 1].end
        pos = toks[lo].start if lo < len(toks) else (toks[-1].end if toks else 0)
        return pos, pos

    diffs = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            continue
        a0, a1 = region(src_tok, i1, i2)
        b0, b1 = region(tgt_tok, j1, j2)
        kinds = sorted(
            {s.type for s in _overlapping(src_spans, a0, a1)}
            | {s.type for s in _overlapping(tgt_spans, b0, b1)}
        )
        diffs.append(
            {
                "op": op,
                "types": kinds,
                "source": {"text": src_text[a0:a1], "start": a0, "end": a1},
                "target": {
                    "text": tgt_text[b0:b1],
                    "start": t_start + b0,
                    "end": t_start + b1,
                },
            }
        )

    def present(spans: list[Span]) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for s in spans:
            out.setdefault(s.type, []).append(s.text)
        return out

    return {
        "backend": nlp_backend(),
        "similarity": round(matcher.ratio(), 3),
        "target_sentence": {"text": tgt_text, "start": t_start, "end": t_end},
        "source_spans": [asdict(s) for s in src_spans],
        "target_spans": [
            {**asdict(s), "start": t_start + s.start, "end": t_start + s.end} for s in tgt_spans
        ],
        "only_in_source": _only_in(present(src_spans), present(tgt_spans)),
        "only_in_target": _only_in(present(tgt_spans), present(src_spans)),
        "diffs": diffs,
    }


def _only_in(a: dict[str, list[str]], b: dict[str, list[str]]) -> list[str]:
    """Span types present on one side and absent on the other (e.g. an EXCEPTION only in a)."""
    return sorted(k for k in a if k not in b and k in (*SCOPE_TYPES, "NEGATION", "VALUE"))


def typed_target_span(diff: dict, inside: tuple[int, int], types: tuple[str, ...]) -> dict | None:
    """Smallest typed target region of the diff inside [inside), for a minimal patch locator."""
    lo, hi = inside
    for d in sorted(diff["diffs"], key=lambda d: d["target"]["end"] - d["target"]["start"]):
        t = d["target"]
        if (
            set(d["types"]) & set(types)
            and t["end"] > t["start"]
            and lo <= t["start"]
            and t["end"] <= hi
        ):
            return t
    return None


def compact(diff: dict, limit: int = 8) -> list[dict]:
    """Short form for LLM prompts and stored checks."""
    return [
        {
            "op": d["op"],
            "types": d["types"],
            "nguon": d["source"]["text"][:120],
            "noi_bo": d["target"]["text"][:120],
        }
        for d in diff["diffs"]
        if d["types"]
    ][:limit]
