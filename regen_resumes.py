"""Regenerate the tailored RESUME (only) for every existing package with the
fill-the-page logic. Keeps the existing cover letter. No cover-letter LLM call.
"""

import sys
from pathlib import Path

from pipeline import db, research, tailor

APPS = Path(__file__).resolve().parent / "data" / "applications"


def main():
    from docx import Document
    conn = db.connect()
    for folder in sorted(APPS.glob("*")):
        docx = folder / "resume_tailored.docx"
        if not docx.is_file():
            continue
        # skip resumes already filled out (>=10 experience bullets) unless --force
        if "--force" not in sys.argv:
            try:
                n = len(tailor._bullet_blocks(Document(docx))[0])
                if n >= 10:
                    continue
            except Exception:
                pass
        try:
            job_id = int(folder.name.split("-")[0])
        except ValueError:
            continue
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            print(f"  skip {folder.name}: no db row")
            continue
        brief = ""
        bf = folder / "company_brief.md"
        if bf.exists():
            brief = bf.read_text(encoding="utf-8-sig")
        else:
            brief = research.company_brief(row["company"], row["title"])
        try:
            plan = tailor.tailor_resume(dict(row), folder / "resume_tailored.docx", brief=brief)
            from docx2pdf import convert
            convert(str(folder / "resume_tailored.docx"),
                    str(folder / "resume_tailored.pdf"))
            print(f"  regenerated {folder.name}: {len(plan.experience_bullets)} bullets")
        except Exception as exc:
            print(f"  ! {folder.name}: {exc}")


if __name__ == "__main__":
    main()
