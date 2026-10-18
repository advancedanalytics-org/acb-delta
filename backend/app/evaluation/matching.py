"""Matching rules used by the metrics (KHOA-01).

Legal text gives a natural key: a clause is identified by where it sits in the document
(Điều / Khoản / Điểm). Matching on that normalized path keeps the metrics deterministic, which
fuzzy text similarity would not -- two runs of the same pipeline must score the same.

`"Điều 3, khoản 1, điểm a"` and `"điều 3 khoản 1 điểm a"` both normalize to `"3.1.a"`.
"""

import re
import unicodedata

# Each level contributes one dot-separated component, in document order.
_LEVELS: tuple[re.Pattern[str], ...] = (
    re.compile(r"đi[eề]u\s*(\d+)", re.IGNORECASE),
    re.compile(r"kho[aả]n\s*(\d+)", re.IGNORECASE),
    re.compile(r"đi[eể]m\s*([a-zđ])", re.IGNORECASE),
)


def normalize_article_path(raw: str) -> str:
    """Reduce a Vietnamese clause reference to a comparable path such as `"3.1.a"`.

    Input that carries no recognizable level (already-normalized `"3.1"`, or a label this does not
    know) is returned lowercased with whitespace collapsed, so it still compares equal to itself.
    """
    text = unicodedata.normalize("NFC", raw)
    parts = [match.group(1).lower() for pattern in _LEVELS if (match := pattern.search(text))]
    if parts:
        return ".".join(parts)
    return re.sub(r"\s+", " ", text).strip().lower()


def impact_key(change_path: str, chunk_id: str) -> tuple[str, str]:
    """Identity of an impact: which change hit which internal-document chunk.

    `type` and `severity` are deliberately not part of the key. Detection and labelling are
    measured separately because missing an impact is the expensive error, while labelling it
    `conflict` instead of `new_obligation` is cheap to fix in review (PLAN.md KHOA-01 prioritises
    Recall).
    """
    return normalize_article_path(change_path), chunk_id.strip()
