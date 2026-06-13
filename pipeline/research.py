"""Company research brief, fed into resume summary + cover letter generation.

A short web-researched brief on what the company does, its product, and any
angle a candidate could speak to. Cached per company in data/company_briefs/
so we research each company once, not once per posting. Degrades to "" on any
failure - the pipeline still generates, just without the company-specific edge.
"""

import re
from pathlib import Path

from . import llm

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "company_briefs"


def _slug(company):
    return re.sub(r"[^a-z0-9]+", "-", (company or "").lower()).strip("-")[:50] or "unknown"


def company_brief(company: str, title: str = "") -> str:
    if not company:
        return ""
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{_slug(company)}.md"
    if cached.exists():
        return cached.read_text(encoding="utf-8-sig")

    prompt = f"""Write a tight brief (max 120 words) on the company "{company}" for someone
applying to a {title or 'role'} there. Cover: what the company does and its product, the
domain/industry, and 1-2 specific things a candidate could authentically connect to.
Output ONLY the brief itself - plain factual prose, no preamble, no meta-commentary about
your sources or capabilities, no "---" separators, no headers. If you genuinely don't know
the company, output exactly: UNKNOWN"""
    try:
        brief = _clean(llm.complete_text(prompt))
    except Exception:
        return ""
    if not brief or brief.upper().startswith("UNKNOWN") or len(brief) < 40:
        brief = ""
    cached.write_text(brief, encoding="utf-8-sig")
    return brief


def _clean(text):
    """Strip meta-preamble, --- separators, and capability disclaimers."""
    parts = re.split(r"^---\s*$", text, flags=re.MULTILINE)
    if len(parts) >= 2:
        text = max(parts, key=len)  # the real brief is the longest segment
    lines = []
    for line in text.strip().splitlines():
        low = line.lower()
        if any(p in low for p in ("web search", "i wasn't able", "i couldn't", "based on",
                                  "draws on", "as of my", "my knowledge", "permission")):
            continue
        lines.append(line)
    return "\n".join(lines).strip()
