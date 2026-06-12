"""Discovery layer: JobSpy for anonymous board scraping (breadth) plus direct
Greenhouse/Lever/Ashby public JSON endpoints (freshness, no scraping).
Everything is normalized to one job dict shape before ingest."""

import math

import requests

HOURLY_TO_YEARLY = 2080


def _s(value):
    """pandas gives NaN (a truthy float) for missing strings - coerce to ''."""
    return value if isinstance(value, str) else ""


def _annualize(amount, interval):
    if amount is None or (isinstance(amount, float) and math.isnan(amount)):
        return None
    interval = (interval or "yearly").lower()
    factor = {"yearly": 1, "monthly": 12, "weekly": 52, "daily": 260, "hourly": HOURLY_TO_YEARLY}.get(interval, 1)
    return float(amount) * factor


def discover_jobspy(terms, sites, locations=("Remote",), hours_old=168, results_wanted=15):
    """Scrape job boards anonymously via JobSpy, sweeping every term across
    every configured metro (plus remote). No accounts, no login."""
    from jobspy import scrape_jobs  # deferred: heavy import

    jobs = []
    searches = [(term, loc) for term in terms for loc in locations]
    for i, (term, loc) in enumerate(searches, 1):
        remote = loc.lower() == "remote"
        print(f"  [{i}/{len(searches)}] {term} @ {loc}")
        try:
            df = scrape_jobs(
                site_name=list(sites), search_term=term,
                location="United States" if remote else loc,
                is_remote=remote, hours_old=hours_old, results_wanted=results_wanted,
            )
        except Exception as exc:  # one search failing should not sink the run
            print(f"  ! jobspy failed for {term!r} @ {loc!r}: {exc}")
            continue
        for row in df.to_dict("records"):
            yearly_min = _annualize(row.get("min_amount"), row.get("interval"))
            jobs.append({
                "title": _s(row.get("title")),
                "company": _s(row.get("company")),
                "location": _s(row.get("location")),
                "is_remote": bool(row.get("is_remote")),
                "salary_min": row.get("min_amount"),
                "salary_max": row.get("max_amount"),
                "salary_yearly_min": yearly_min,
                "salary_source": "listed" if yearly_min else "unknown",
                "url": _s(row.get("job_url")),
                "source": _s(row.get("site")),
                "date_posted": str(row.get("date_posted") or ""),
                "description": _s(row.get("description")),
            })
    return jobs


def discover_greenhouse(board_token):
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    jobs = []
    for j in resp.json().get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        jobs.append({
            "title": j.get("title") or "",
            "company": board_token,
            "location": loc,
            "is_remote": "remote" in loc.lower(),
            "salary_yearly_min": None,
            "salary_source": "unknown",
            "url": j.get("absolute_url"),
            "source": f"greenhouse:{board_token}",
            "date_posted": (j.get("updated_at") or "")[:10],
            "description": j.get("content"),
        })
    return jobs


def discover_lever(org):
    url = f"https://api.lever.co/v0/postings/{org}?mode=json"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    jobs = []
    for j in resp.json():
        cats = j.get("categories") or {}
        loc = cats.get("location") or ""
        jobs.append({
            "title": j.get("text") or "",
            "company": org,
            "location": loc,
            "is_remote": "remote" in loc.lower(),
            "salary_yearly_min": None,
            "salary_source": "unknown",
            "url": j.get("hostedUrl"),
            "source": f"lever:{org}",
            "date_posted": "",
            "description": j.get("descriptionPlain"),
        })
    return jobs


def discover_ashby(org):
    url = f"https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    jobs = []
    for j in resp.json().get("jobs", []):
        comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
        jobs.append({
            "title": j.get("title") or "",
            "company": org,
            "location": j.get("location") or "",
            "is_remote": bool(j.get("isRemote")),
            "salary_yearly_min": None,
            "salary_source": "listed" if comp else "unknown",
            "url": j.get("jobUrl"),
            "source": f"ashby:{org}",
            "date_posted": (j.get("publishedAt") or "")[:10],
            "description": (j.get("descriptionPlain") or "") + ("\n" + comp if comp else ""),
        })
    return jobs


def discover_ats(companies: dict):
    """companies: {"greenhouse_boards": [...], "lever_orgs": [...], "ashby_orgs": [...]}"""
    jobs = []
    fetchers = [("greenhouse_boards", discover_greenhouse),
                ("lever_orgs", discover_lever),
                ("ashby_orgs", discover_ashby)]
    for key, fn in fetchers:
        for org in companies.get(key, []):
            try:
                jobs.extend(fn(org))
            except Exception as exc:
                print(f"  ! {key[:-1]} {org!r} failed: {exc}")
    return jobs
