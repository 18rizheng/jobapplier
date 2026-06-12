# jobapplier

Automated job application pipeline: discovers fresh $100k+ postings daily, scores them against three resume personas, queues them for human approval, then submits applications through ATS-specific automation.

## Pipeline

```
ATS APIs (Greenhouse/Lever/Ashby) ─┐
Aggregators (JobSpy) ──────────────┼─► ingest + dedup ─► scoring engine ─► review queue
Targeted career pages ─────────────┘        (SQLite)    (LLM fit/persona)  (human approves)
                                                              ▲                  │
                                                              │           ┌──────┴──────┐
                                                       feedback loop      ▼             ▼
                                                              │      auto-submit    assisted
                                                              │      (Playwright)  (Claude in
                                                              │                      Chrome)
                                                              └──── outcome tracker ◄┘
```

## Key decisions

- **Fresh build**, borrowing patterns from [ApplyPilot](https://github.com/Pickle-Pixel/ApplyPilot) (3-tier description extraction, structured profile) — see [docs/DESIGN.md](docs/DESIGN.md)
- **Hybrid apply engine**: headless Playwright adapters for Greenhouse/Lever/Ashby; Claude in Chrome for Workday and one-off portals
- **Discovery**: [JobSpy](https://github.com/speedyapply/JobSpy) (anonymous board scraping) + direct ATS JSON APIs; no logged-in LinkedIn automation
- **Human in the loop**: every batch is approved in the review queue before submission — applications are one-shot
- **Daily cadence**, fit-score threshold instead of a volume quota

## Hard rules

1. Tailoring reorders and emphasizes — it never fabricates experience.
2. EEO/demographic answers are fixed by the user once, never guessed.
3. No application is submitted without explicit batch approval.
4. Resume files, `profile.json`, and the SQLite database stay out of git (see `.gitignore`).

## Setup

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install python-jobspy --no-deps   # its numpy pin breaks Python 3.13+
```

Requires `data/profile.json` (see [docs/profile.example.json](docs/profile.example.json)) and resume PDFs in `data/resumes/` — both gitignored, never committed.

## Run

```powershell
.venv\Scripts\python run_discovery.py        # discover -> dedup -> score -> ranked list
```

Search terms, boards, and ATS company lists live in [config/searches.json](config/searches.json). Output: console top-20 plus `data/ranked_latest.csv`.

## Status

- [x] Design (2026-06-11) — see [docs/DESIGN.md](docs/DESIGN.md)
- [x] Master profile parsed from three resumes (persona-tagged bullets, answer bank)
- [x] Phase 1: discovery (JobSpy + Greenhouse/Lever/Ashby pollers) → SQLite ingest/dedup → heuristic scoring → ranked list. Verified live: 60 postings, 51 new, real $100k+ matches ranked.
- [ ] LLM scoring (Claude reads full description vs persona; salary estimation for unlisted)
- [ ] Answer bank completion (sponsorship, salary expectation, remote/relocation — user input)
- [ ] Phase 2: prefill + review queue
- [ ] Phase 3: auto-submit adapters (Greenhouse → Lever → Ashby)
