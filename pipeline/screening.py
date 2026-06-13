"""Grounded answers to a posting's bespoke screening questions.

The static answer bank covers the recurring questions (sponsorship, salary,
location...). Each company also asks a few custom ones - "Do you have
experience with X?", "Years in Y?" - that the bank can't anticipate. This
module asks the LLM for honest, corpus-grounded answers to a batch of those,
returning a yes/no/short-text value per question. EEO/demographic and
identity-category questions are never sent here (the adapter filters them).

During probation every filled form is human-reviewed before sending, so
proposed answers are visible. The values are conservative by instruction:
when the corpus doesn't support a yes, the answer is no.
"""

import json
from pathlib import Path

from pydantic import BaseModel

from . import llm

ROOT = Path(__file__).resolve().parent.parent
FACTS = ROOT / "data" / "facts.md"


class ScreeningAnswers(BaseModel):
    answers: dict[str, str]   # question text -> "Yes" | "No" | short answer


def answer_questions(questions: list[str], row) -> dict[str, str]:
    if not questions:
        return {}
    facts = FACTS.read_text(encoding="utf-8-sig")
    numbered = "\n".join(f"{i}. {q}" for i, q in enumerate(questions))
    schema_note = ("\n\nRespond with ONLY a JSON object, no fences, exactly: "
                   '{"answers": {"<exact question text>": "<Yes|No|short answer>"}}. '
                   "Include every question. Default to No when the corpus does not clearly "
                   "support Yes. For numeric/years questions give a number. Keep free-text "
                   "answers under 15 words.")
    prompt = f"""Answer these employer screening questions for a candidate, honestly and
conservatively, using ONLY the fact corpus. These gate an application, so a wrong Yes is
worse than an honest No. For "do you have experience with X" questions, answer Yes only
if the corpus clearly shows it; otherwise No. Never invent experience.

FACT CORPUS:
{facts}

APPLYING TO: {row['title']} at {row['company']}

QUESTIONS:
{numbered}"""
    try:
        result = llm.complete_json(prompt, ScreeningAnswers, schema_note)
        return result.answers
    except Exception:
        return {}
