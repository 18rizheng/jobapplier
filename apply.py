"""Apply orchestrator - the last mile over packaged-and-ready jobs.

Lanes:
  auto     ATS-direct postings (Greenhouse today): Playwright fills the form
           from answers.json, uploads the resume, screenshots. With
           submit=True it actually submits - after a silent pre-send honesty
           check (pipeline/sendcheck.py) and only when zero required questions
           are unmapped.
  assisted login-walled portals: writes assist.md checklist; --open launches
           the posting in the browser.

Indeed postings are first resolved to the company's own application URL where
possible, upgrading them to the auto lane.

Usage:  .venv\\Scripts\\python apply.py [--submit] [--open] [--id N]
"""

import json
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from pipeline import db, resolve
from pipeline.adapters import greenhouse

ROOT = Path(__file__).resolve().parent
APPS = ROOT / "data" / "applications"


def detect_lane(url):
    return "auto" if "greenhouse.io" in (url or "") else "assisted"


def effective_url(conn, row):
    """Resolved company-site URL when available; resolves Indeed links once."""
    if row["ats_url"]:
        return None if row["ats_url"] == "unresolvable" else row["ats_url"]
    if "indeed.com" not in (row["url"] or ""):
        return row["url"]
    resolved = resolve.resolve_indeed(row["url"])
    conn.execute("UPDATE jobs SET ats_url=? WHERE id=?",
                 (resolved or "unresolvable", row["id"]))
    conn.commit()
    return resolved


def write_assist(folder, row, answers):
    from urllib.parse import quote
    locked = "\n".join(f"- {k}: {v}" for k, v in answers["answers"].items())
    referral = ("https://www.linkedin.com/search/results/people/?keywords="
                + quote(row["company"] or ""))
    (folder / "assist.md").write_text(
        f"# Assisted application: {row['title']} - {row['company']}\n\n"
        f"0. BEFORE applying, check for connections (referrals beat every other channel):\n"
        f"   {referral}\n"
        f"1. Open: {row['url']}\n"
        f"2. Attach: {answers['resume_file']} (in this folder)\n"
        f"3. Cover letter: cover_letter.md (in this folder)\n"
        f"4. Screening answers (locked canonical values):\n{locked}\n\n"
        f"Contact: {answers['contact']['full_name']} | {answers['contact']['email']} | "
        f"{answers['contact']['phone']}\n\n"
        f"After submitting, record it:  .venv\\Scripts\\python track.py applied {row['id']}\n",
        encoding="utf-8-sig")


def main(submit=False, prepare=False, open_browser=False, only_id=None):
    """submit: actually send (autonomy lane / dashboard-approved single job).
    prepare: fill + screenshot + screening, hold in awaiting_send, never send."""
    conn = db.connect()
    rows = conn.execute("SELECT * FROM jobs WHERE status='reviewed'").fetchall()
    if only_id:
        rows = [r for r in rows if r["id"] == only_id]
    mode = ("AUTONOMOUS" if db.autonomy_unlocked(conn) else
            f"PROBATION {db.approved_send_count(conn)}/{db.PROBATION_SENDS}") \
        if submit else ("prepare-and-hold" if prepare else "dry run")
    print(f"{len(rows)} ready jobs ({mode})")
    sent = blocked = assisted = held = 0

    for row in rows:
        folders = list(APPS.glob(f"{row['id']}-*"))
        if not folders:
            print(f"  ! no folder for job {row['id']}")
            continue
        folder = folders[0]
        answers = json.loads((folder / "answers.json").read_text(encoding="utf-8-sig"))
        target = effective_url(conn, row)
        lane = detect_lane(target)
        print(f"  [{lane}] {folder.name}")

        if lane == "auto" and target:
            # 'prepare' never submits; 'submit' submits only when allowed by probation
            really_submit = submit and (db.autonomy_unlocked(conn) or row["send_approved"])
            if really_submit:
                from pipeline import sendcheck
                profile = json.loads((ROOT / "data" / "profile.json")
                                     .read_text(encoding="utf-8-sig"))
                if not sendcheck.ensure_sendable(folder, row, profile):
                    print("    skipped - pre-send check could not verify materials")
                    blocked += 1
                    continue
            report = greenhouse.apply_greenhouse(target, folder, answers,
                                                 submit=really_submit, headless=True,
                                                 row=dict(row))
            if report["submitted"]:
                conn.execute(
                    "UPDATE jobs SET status='applied', applied_at=? WHERE id=?",
                    (datetime.now(timezone.utc).isoformat(timespec='seconds'), row["id"]))
                conn.commit()
                sent += 1
                print("    SUBMITTED")
            elif really_submit and report["unmapped_required"]:
                # autonomy lane couldn't complete it headlessly - leave for the human
                print(f"    blocked on required questions: {report['unmapped_required'][:3]}")
                blocked += 1
            elif really_submit and not report.get("submit_verified", True):
                # we clicked submit but could NOT confirm it went through - never
                # claim 'applied'. Hold for the human to verify via the screenshot.
                conn.execute("UPDATE jobs SET status='awaiting_send' WHERE id=?", (row["id"],))
                conn.commit()
                held += 1
                print(f"    UNCONFIRMED submit - held for you to verify: "
                      f"{folder.name}\\form_submitted.png")
            elif prepare or submit:
                # probation (or a held job): surface it for review even if a field
                # still needs the human - the card shows what's left
                conn.execute("UPDATE jobs SET status='awaiting_send' WHERE id=?", (row["id"],))
                conn.commit()
                held += 1
                tail = (" - needs you to finish: " + str(report["unmapped_required"][:2])
                        if report["unmapped_required"] else "")
                print(f"    HELD for approval ({db.approved_send_count(conn)}/"
                      f"{db.PROBATION_SENDS}){tail}")
            else:
                print(f"    filled (dry): see {folder.name}\\form_filled.png")
        else:
            write_assist(folder, row, answers)
            assisted += 1
            if open_browser:
                webbrowser.open(row["url"])
            print(f"    checklist: {folder.name}\\assist.md")

    print(f"\nsubmitted {sent}, held for approval {held}, "
          f"blocked {blocked}, assisted checklists {assisted}")


if __name__ == "__main__":
    only = int(sys.argv[sys.argv.index("--id") + 1]) if "--id" in sys.argv else None
    main(submit="--submit" in sys.argv, prepare="--prepare" in sys.argv,
         open_browser="--open" in sys.argv, only_id=only)
