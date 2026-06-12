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


def pick_resume(row, profile, folder, score):
    """Returns the resume file path placed in the folder, per the tailoring rule."""
    if score >= TAILOR_THRESHOLD and tailor.TEMPLATE.exists():
        out = folder / "resume_tailored.docx"
        plan = tailor.tailor_resume(dict(row), out)
        (folder / "tailoring.md").write_text(
            f"# Tailoring plan\n\n{plan.rationale}\n\n"
            f"- experience order: {plan.experience_order}\n"
            f"- skills order: {plan.skills_order}\n\n"
            f"Reorder-only of vetted bullets from data/resumes/general.docx - no new text.\n",
            encoding="utf-8-sig")
        return out
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


def write_cover_letter(folder, row, profile):
    prompt = f"""Write a cover letter for this application. 150-200 words, three short
paragraphs, plain confident tone. No "I am writing to express", no flattery, no
fabrication - only facts from the background below. Name 1-2 specific overlaps
between the background and the posting. Output ONLY the letter body - no header,
no preamble like "Here's the letter", no separators, no commentary after.

BACKGROUND:
Quality Manager on Epic Systems' EDI team since Sept 2022. Owns end-to-end QA for
healthcare integration software (HL7v2, FHIR, EDI) - 665 changes, 146 projects,
600+ to production. Built multi-agent AI code-review pipelines (Claude Code, Python),
cutting review cost 40-50%. Owns quarterly release testing across two product teams.
Requirements gathering with international customers (Denmark, on-site). Mentors staff,
teaches internal classes. BS Biochemistry UCLA 2022; CS capstone at UW-Madison in progress.

POSTING:
Title: {row['title']}
Company: {row['company']}
Description:
{(row['description'] or '')[:4000]}"""
    letter = clean_letter(llm.complete_text(prompt))
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
        print(f"  {folder.name} (score {score}{', tailoring' if score >= TAILOR_THRESHOLD else ''})")
        try:
            write_job_md(folder, row)
            resume_path = pick_resume(row, profile, folder, score)
            write_cover_letter(folder, row, profile)
            write_answers(folder, row, profile, resume_path)
        except Exception as exc:
            print(f"  ! failed: {exc}")
            continue
        conn.execute("UPDATE jobs SET status='packaged' WHERE id=?", (row["id"],))
        conn.commit()

    print("done - review folders under data/applications/ before applying")


if __name__ == "__main__":
    main()
