"""Package approved (queued) jobs into application folders under
data/applications/<id>-<company>/ containing:

  job.md           posting details + full description
  resume           tailored docx (score >= 7) or persona PDF as-is (5-7),
                   per the tailoring rule in docs/DESIGN.md
  tailoring.md     the reorder rationale (review diff), when tailored
  cover_letter.md  drafted from the profile + posting, for review/editing
  answers.json     locked answer-bank values + contact info for form filling

Usage:  .venv\\Scripts\\python package.py
"""

import json
import re
import shutil
import sys
from pathlib import Path

from pipeline import db, llm, tailor

ROOT = Path(__file__).resolve().parent
APPS = ROOT / "data" / "applications"
TAILOR_THRESHOLD = 7.0


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40] or "unknown"


def write_job_md(folder, row):
    score = row["llm_score"] if row["llm_score"] is not None else row["fit_score"]
    (folder / "job.md").write_text(
        f"# {row['title']} - {row['company']}\n\n"
        f"- Score: {score} ({row['persona']})\n"
        f"- Location: {row['location']} (remote: {bool(row['is_remote'])})\n"
        f"- Salary: listed min {row['salary_yearly_min']}, estimate {row['llm_salary_estimate']}\n"
        f"- URL: {row['url']}\n"
        f"- Source: {row['source']} | first seen {row['first_seen']}\n\n"
        f"## Assessment\n{row['llm_reason'] or row['score_reason']}\n\n"
        f"## Knockout risks\n{row['knockout_risks'] or 'none flagged'}\n\n"
        f"## Description\n{row['description'] or '(not captured)'}\n",
        encoding="utf-8-sig")


def pick_resume(row, profile, folder, score, brief=""):
    """Generated tailored resume for every approved job (rule changed 2026-06-11);
    persona PDF only as a fallback when generation fails."""
    if tailor.TEMPLATE.exists():
        try:
            out = folder / "resume_tailored.docx"
            plan = tailor.tailor_resume(dict(row), out, brief=brief)
            # tailor_resume already rendered the PDF during the length guard
            if out.with_suffix(".pdf").exists():
                out = out.with_suffix(".pdf")
            bullets = "\n".join(f"- {b}" for b in plan.experience_bullets)
            (folder / "tailoring.md").write_text(
                f"# Tailoring plan\n\n{plan.rationale}\n\n"
                f"## Generated bullets\n{bullets}\n\n"
                f"## Skills lines\n" + "\n".join(f"- {s}" for s in plan.skills_lines) + "\n\n"
                f"Generated from data/facts.md{' + company brief' if brief else ''}.\n",
                encoding="utf-8-sig")
            return out
        except Exception as exc:
            print(f"  ! tailoring failed ({exc}); falling back to persona PDF")
    persona = row["persona"] if row["persona"] in ("technical", "analyst_pm") else "general"
    src_name = profile["personas"][persona].get("resume_file") or "data/resumes/general.pdf"
    src = ROOT / src_name
    dest = folder / f"resume_{persona}.pdf"
    shutil.copy(src, dest)
    return dest


def clean_letter(text):
    """Strip LLM chatter: preamble lines, --- separators, trailing commentary."""
    parts = re.split(r"^---\s*$", text, flags=re.MULTILINE)
    if len(parts) >= 3:
        text = parts[1]
    lines = text.strip().splitlines()
    if lines and lines[0].strip().endswith(":") and len(lines[0]) < 80:
        lines = lines[1:]
    return "\n".join(lines).strip() + "\n"


def write_cover_letter(folder, row, profile, brief=""):
    facts = (ROOT / "data" / "facts.md").read_text(encoding="utf-8-sig")
    brief_block = f"\nCOMPANY BRIEF (reference something specific from this):\n{brief}\n" if brief else ""
    prompt = f"""Write a cover letter for this application. 150-200 words, three short
paragraphs, plain confident tone. No "I am writing to express", no flattery.
WRITE LIKE A HUMAN, NOT AN AI: never use em dashes or en dashes (use commas/periods,
and "to" for ranges); use straight quotes; ban these tell-tale words: leverage, utilize,
spearhead, passionate, seamless, robust, cutting-edge, delve, tapestry, testament,
synergy, foster, realm, landscape, elevate, unlock, empower, crucial, pivotal, thrilled,
excited to, deeply. No "not only X but also Y". Vary sentence length, use plain verbs.
THE FIRST SENTENCE must name {row['company']} and state the single most compelling,
specific overlap between the candidate and this exact role - recruiters decide in one
line whether to keep reading. If a company brief is given, reference something specific
and real about the company. TWO grounding rules, both strict:
- Claims about the CANDIDATE must trace to the FACT CORPUS (rephrasing/posting vocabulary
  fine, new facts not).
- Claims about the COMPANY must trace to the COMPANY BRIEF or posting. NEVER invent
  specifics about the company's tools, tech stack, or how they work to manufacture a
  connection (e.g. do not claim they use a tool just because the candidate knows it).
  Connect via the company's stated mission/domain and the candidate's real strengths.
Output ONLY the letter body - no header, no preamble.
{brief_block}
FACT CORPUS:
{facts[:6000]}

POSTING:
Title: {row['title']}
Company: {row['company']}
Description:
{(row['description'] or '')[:4000]}"""
    from pipeline import destyle
    letter = destyle.de_ai(clean_letter(llm.complete_text(prompt)))
    (folder / "cover_letter.md").write_text(letter, encoding="utf-8-sig")


def write_answers(folder, row, profile, resume_path):
    bank = {k: v["value"] for k, v in profile["answer_bank"].items() if v.get("locked")}
    (folder / "answers.json").write_text(json.dumps({
        "contact": profile["contact"],
        "answers": bank,
        "resume_file": resume_path.name,
        "persona": row["persona"],
        "unlocked_answers_blocked": [k for k, v in profile["answer_bank"].items()
                                     if not v.get("locked")],
    }, indent=2), encoding="utf-8-sig")


def main():
    profile = json.loads((ROOT / "data" / "profile.json").read_text(encoding="utf-8-sig"))
    conn = db.connect()
    rows = conn.execute("SELECT * FROM jobs WHERE status = 'queued'").fetchall()
    print(f"packaging {len(rows)} approved jobs")

    for row in rows:
        folder = APPS / f"{row['id']}-{slugify(row['company'])}"
        folder.mkdir(parents=True, exist_ok=True)
        score = row["llm_score"] if row["llm_score"] is not None else row["fit_score"]
        print(f"  {folder.name} (score {score})")
        try:
            from pipeline import research
            brief = research.company_brief(row["company"], row["title"])
            if brief:
                (folder / "company_brief.md").write_text(brief, encoding="utf-8-sig")
            write_job_md(folder, row)
            resume_path = pick_resume(row, profile, folder, score, brief)
            write_cover_letter(folder, row, profile, brief)
            write_answers(folder, row, profile, resume_path)
        except Exception as exc:
            print(f"  ! failed: {exc}")
            continue
        # no automated gate (removed 2026-06-12) - the human is the reviewer of record
        conn.execute("UPDATE jobs SET status='reviewed' WHERE id=?", (row["id"],))
        conn.commit()

    print("done - inspect folders under data/applications/ before applying")


if __name__ == "__main__":
    main()
