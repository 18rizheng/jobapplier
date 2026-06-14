"""Local dashboard for the job application pipeline.

Run:  .venv\\Scripts\\python app.py   ->  http://localhost:5713
"""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from flask import Flask, abort, jsonify, render_template, request, send_from_directory

from pipeline import db

ROOT = Path(__file__).resolve().parent
APPS = ROOT / "data" / "applications"

app = Flask(__name__)


def _folder_for(job_id: int):
    matches = list(APPS.glob(f"{job_id}-*"))
    return matches[0] if matches else None


def _read(folder, name, limit=20000):
    f = folder / name
    if f and f.exists():
        return f.read_text(encoding="utf-8-sig")[:limit]
    return None


@app.route("/")
def dashboard():
    conn = db.connect()
    counts = {r["status"]: r["c"] for r in conn.execute(
        "SELECT status, COUNT(*) c FROM jobs GROUP BY status")}
    total = sum(counts.values())

    queue = [dict(r) for r in conn.execute(
        """SELECT * FROM jobs WHERE status='scored'
           AND COALESCE(llm_score, fit_score) >= 5
           ORDER BY llm_score IS NULL, COALESCE(llm_score, fit_score) DESC,
                    date_posted DESC
           LIMIT 60""")]
    from pipeline.scoring import posting_age_days
    for job in queue:
        try:
            job["risks"] = json.loads(job["knockout_risks"] or "[]")
        except (json.JSONDecodeError, TypeError):
            job["risks"] = []
        job["age_days"] = posting_age_days(job.get("date_posted"))

    awaiting = []
    for r in conn.execute(
            "SELECT * FROM jobs WHERE status='awaiting_send' ORDER BY COALESCE(llm_score, fit_score) DESC"):
        job = dict(r)
        folder = _folder_for(job["id"])
        if folder:
            job["folder"] = folder.name
            job["has_preview"] = (folder / "form_filled.png").exists()
            job["cover_letter"] = _read(folder, "cover_letter.md", 4000)
            job["resume_file"] = next(
                (p.name for p in folder.iterdir()
                 if p.name.startswith("resume") and p.suffix == ".pdf"), None)
            try:
                fr = json.loads(_read(folder, "fill_report.json") or "{}")
                job["proposed"] = fr.get("proposed_answers", [])
                job["still_blocked"] = fr.get("unmapped_required", [])
            except (json.JSONDecodeError, TypeError):
                job["proposed"], job["still_blocked"] = [], []
        awaiting.append(job)

    packages = []
    for r in conn.execute(
            """SELECT * FROM jobs WHERE status IN ('reviewed','flagged','packaged','queued','applied')
               ORDER BY CASE status WHEN 'flagged' THEN 0 WHEN 'reviewed' THEN 1
                        WHEN 'packaged' THEN 2 WHEN 'queued' THEN 3 ELSE 4 END,
                        COALESCE(llm_score, fit_score) DESC"""):
        job = dict(r)
        folder = _folder_for(job["id"])
        job["files"] = []
        if folder:
            job["folder"] = folder.name
            job["files"] = sorted(p.name for p in folder.iterdir())
            review = _read(folder, "review.md", 4000) or ""
            job["review_pass"] = "PASS" in review[:40]
            job["review_body"] = review
            job["cover_letter"] = _read(folder, "cover_letter.md", 4000)
        packages.append(job)

    applied = [dict(r) for r in conn.execute(
        "SELECT * FROM jobs WHERE applied_at IS NOT NULL ORDER BY applied_at DESC LIMIT 30")]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
    followups = [j for j in applied if j["outcome"] is None and (j["applied_at"] or "") < cutoff]
    for job in followups:
        job["linkedin_search"] = ("https://www.linkedin.com/search/results/people/?keywords="
                                  + quote(job["company"] or ""))

    approved_sends = db.approved_send_count(conn)
    return render_template(
        "dashboard.html",
        counts=counts, total=total, queue=queue, packages=packages,
        applied=applied, followups=followups, awaiting=awaiting,
        approved_sends=approved_sends, probation=db.PROBATION_SENDS,
        autonomous=db.autonomy_unlocked(conn),
        now=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))


@app.route("/api/jobs/<int:job_id>/<action>", methods=["POST"])
def job_action(job_id, action):
    transitions = {"approve": "queued", "reject": "rejected",
                   "applied": "applied", "unflag": "reviewed"}
    if action not in transitions:
        abort(400)
    conn = db.connect()
    if not conn.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone():
        abort(404)
    if action == "applied":
        conn.execute("UPDATE jobs SET status='applied', applied_at=? WHERE id=?",
                     (datetime.now(timezone.utc).isoformat(timespec="seconds"), job_id))
    else:
        conn.execute("UPDATE jobs SET status=? WHERE id=?", (transitions[action], job_id))
    conn.commit()
    return jsonify({"ok": True, "status": transitions[action]})


@app.route("/api/jobs/<int:job_id>/send", methods=["POST"])
def job_send(job_id):
    """Human approves a fully-filled held application: mark approved and submit headlessly."""
    conn = db.connect()
    if not conn.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone():
        abort(404)
    conn.execute("UPDATE jobs SET send_approved=1, status='reviewed' WHERE id=?", (job_id,))
    conn.commit()
    import apply as apply_mod
    apply_mod.main(submit=True, only_id=job_id)
    row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    ok = row["status"] == "applied"
    if not ok:  # headless submit couldn't complete - leave it for manual finish
        conn.execute("UPDATE jobs SET status='awaiting_send' WHERE id=?", (job_id,))
        conn.commit()
    return jsonify({"ok": ok, "status": "applied" if ok else "needs manual finish"})


@app.route("/api/jobs/<int:job_id>/sent_manual", methods=["POST"])
def job_sent_manual(job_id):
    """Human finished a partially-filled form in their own browser and submitted it.
    Counts toward the probation tally (it was a human-approved send)."""
    conn = db.connect()
    cur = conn.execute("UPDATE jobs SET send_approved=1, status='applied', applied_at=? WHERE id=?",
                       (datetime.now(timezone.utc).isoformat(timespec="seconds"), job_id))
    conn.commit()
    if cur.rowcount == 0:
        abort(404)
    return jsonify({"ok": True, "status": "applied"})


@app.route("/api/jobs/<int:job_id>/outcome/<result>", methods=["POST"])
def job_outcome(job_id, result):
    if result not in ("response", "interview", "offer", "rejected"):
        abort(400)
    conn = db.connect()
    cur = conn.execute("UPDATE jobs SET outcome=?, outcome_at=? WHERE id=?",
                       (result, datetime.now(timezone.utc).isoformat(timespec="seconds"), job_id))
    conn.commit()
    if cur.rowcount == 0:
        abort(404)
    return jsonify({"ok": True, "outcome": result})


@app.route("/favicon.ico")
def favicon():
    # tiny inline SVG favicon (blue dot) - silences the 404, stays on brand
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
           '<circle cx="16" cy="16" r="14" fill="#0071e3"/></svg>')
    return app.response_class(svg, mimetype="image/svg+xml")


@app.route("/upskill")
def upskill_report():
    report = ROOT / "data" / "upskill_report.md"
    text = report.read_text(encoding="utf-8-sig") if report.exists() else \
        "No report yet. Run: .venv\\Scripts\\python upskill.py"
    return render_template("upskill.html", report=text)


@app.route("/files/<int:job_id>/<path:name>")
def job_file(job_id, name):
    folder = _folder_for(job_id)
    if not folder or not re.fullmatch(r"[\w.\- ]+", name):
        abort(404)
    return send_from_directory(folder, name)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5713, debug=False)
