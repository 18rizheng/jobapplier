"""Silent pre-send honesty check - used ONLY inside the unattended send path.

The human-facing fabrication gate was removed (2026-06-12): nothing blocks or
flags packages, and no approval is asked anywhere. This module exists because
fully autonomous submission means no human sees the materials before an
employer does. Before an unattended send, it verifies the generated resume
and letter contain no hard checkable falsehoods (invented employers/titles/
dates/credentials, altered numbers, named-tech proficiency with zero corpus
basis). On failure it regenerates the resume once with the findings as
constraints; if still failing, the job is skipped (left for the next run),
never blocked in the UI.
"""

import json
from pathlib import Path

from pydantic import BaseModel

from . import llm

ROOT = Path(__file__).resolve().parent.parent
FACTS = ROOT / "data" / "facts.md"


class SendCheck(BaseModel):
    ok: bool
    problems: list[str]


_SCHEMA_NOTE = """

Respond with ONLY a JSON object, no markdown fences, matching exactly:
{"ok": <bool>, "problems": [<hard falsehoods only, empty when ok>]}"""


def _resume_text(folder: Path) -> str:
    docx_path = folder / "resume_tailored.docx"
    if not docx_path.exists():
        return ""
    from docx import Document
    return "\n".join(p.text for p in Document(docx_path).paragraphs if p.text.strip())


def check(folder: Path, row) -> SendCheck:
    facts = FACTS.read_text(encoding="utf-8-sig")
    cover = ""
    if (folder / "cover_letter.md").exists():
        cover = (folder / "cover_letter.md").read_text(encoding="utf-8-sig")
    prompt = f"""Final machine check before an UNATTENDED job application submission.
No human will see these materials before the employer does. Report ONLY hard
checkable falsehoods - invented/altered employers, job titles, dates, degrees,
certifications; changed numbers; claimed hands-on proficiency in a named
technology with zero basis in the corpus. Paraphrase, posting keywords,
inference, and framing are all fine. When unsure, it is fine.

FACT CORPUS:
{facts}

POSTING: {row['title']} at {row['company']}

GENERATED RESUME:
{_resume_text(folder)[:3500]}

COVER LETTER:
{cover[:2500]}"""
    return llm.complete_json(prompt, SendCheck, _SCHEMA_NOTE)


def ensure_sendable(folder: Path, row, profile) -> bool:
    """True when safe to send unattended. One regenerate-and-recheck on failure."""
    verdict = check(folder, row)
    if verdict.ok:
        return True
    from . import tailor
    try:
        tailor.tailor_resume(dict(row), folder / "resume_tailored.docx",
                             avoid_issues=verdict.problems)
        try:
            from docx2pdf import convert
            convert(str(folder / "resume_tailored.docx"),
                    str(folder / "resume_tailored.pdf"))
        except Exception:
            pass
        verdict = check(folder, row)
    except Exception:
        return False
    return verdict.ok
