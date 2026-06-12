"""Daily discovery run: scrape -> ingest/dedup -> score -> ranked list.

Usage:  .venv\\Scripts\\python run_discovery.py [--skip-jobspy]
Output: prints top matches, writes data/ranked_latest.csv (gitignored)."""

import csv
import json
import sys
from pathlib import Path

from pipeline import db, discovery, scoring

ROOT = Path(__file__).resolve().parent


def main():
    profile = json.loads((ROOT / "data" / "profile.json").read_text(encoding="utf-8-sig"))
    cfg = json.loads((ROOT / "config" / "searches.json").read_text(encoding="utf-8-sig"))

    print("== discovery ==")
    found = []
    if "--skip-jobspy" not in sys.argv:
        js = cfg["jobspy"]
        terms = [t for persona_terms in js["terms"].values() for t in persona_terms]
        print(f"jobspy: {len(terms)} terms x {len(js['locations'])} locations on {js['sites']}")
        found += discovery.discover_jobspy(
            terms, js["sites"], js["locations"], js["hours_old"], js["results_wanted"])
    ats_jobs = discovery.discover_ats(cfg["ats"])
    if ats_jobs:
        print(f"ats endpoints: {len(ats_jobs)} postings")
    found += ats_jobs
    print(f"discovered {len(found)} postings")

    print("== ingest ==")
    conn = db.connect()
    new_count = sum(1 for job in found if job["title"] and job["company"] and db.upsert_job(conn, job))
    conn.commit()
    print(f"{new_count} new, {len(found) - new_count} already seen")

    print("== scoring ==")
    rows = conn.execute("SELECT * FROM jobs WHERE status = 'new'").fetchall()
    for row in rows:
        persona, score, reason, gate = scoring.score_job(dict(row), profile)
        status = "rejected" if gate == "fail" else "scored"
        conn.execute(
            "UPDATE jobs SET persona=?, fit_score=?, score_reason=?, status=? WHERE id=?",
            (persona, score, reason, status, row["id"]))
    conn.commit()
    print(f"scored {len(rows)} new jobs")

    llm_cfg = cfg.get("llm_scoring", {})
    if llm_cfg.get("enabled") and "--skip-llm" not in sys.argv:
        from pipeline import llm

        candidates = conn.execute(
            """SELECT * FROM jobs WHERE status = 'scored' AND llm_score IS NULL
               AND fit_score >= ? ORDER BY fit_score DESC LIMIT ?""",
            (llm_cfg.get("heuristic_threshold", 4.0),
             llm_cfg.get("max_jobs_per_run", 30))).fetchall()
        print(f"== llm scoring ({len(candidates)} candidates) ==")
        for i, row in enumerate(candidates, 1):
            try:
                a = llm.assess_job(dict(row), profile, llm_cfg.get("model", llm.DEFAULT_MODEL))
            except Exception as exc:
                print(f"  ! [{i}/{len(candidates)}] {row['title'][:40]}: {exc}")
                continue
            status = "scored" if a.meets_salary_floor else "rejected"
            conn.execute(
                """UPDATE jobs SET llm_score=?, llm_reason=?, llm_salary_estimate=?,
                       knockout_risks=?, persona=?, status=? WHERE id=?""",
                (a.fit_score, a.reason, a.salary_estimate_usd,
                 json.dumps(a.knockout_risks), a.persona, status, row["id"]))
            conn.commit()
            print(f"  [{i}/{len(candidates)}] {a.fit_score:>4} {row['title'][:44]:<44} {a.persona}")

    ranked = conn.execute(
        """SELECT title, company, location, salary_yearly_min, persona,
                  COALESCE(llm_score, fit_score) AS fit_score,
                  COALESCE(llm_reason, score_reason) AS score_reason, url, source
           FROM jobs WHERE status = 'scored'
           ORDER BY llm_score IS NULL, fit_score DESC LIMIT 50""").fetchall()

    out = ROOT / "data" / "ranked_latest.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["title", "company", "location", "salary_yearly_min", "persona",
                         "fit_score", "score_reason", "url", "source"])
        writer.writerows([tuple(r) for r in ranked])

    print(f"\n== top matches (full list: {out}) ==")
    for r in ranked[:20]:
        sal = f"${r['salary_yearly_min']:,.0f}+" if r["salary_yearly_min"] else "salary ?"
        print(f"  [{r['fit_score']:>4}] {r['persona'] or '-':<10} {r['title'][:48]:<48} "
              f"{r['company'][:24]:<24} {sal}")


if __name__ == "__main__":
    main()
