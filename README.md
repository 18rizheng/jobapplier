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
- [x] LLM scoring: Claude reads the full description vs the profile — fit 0–10, salary estimation for unlisted postings, knockout-risk detection. Backends: Anthropic SDK (`ANTHROPIC_API_KEY` in `.env`) or `claude` CLI fallback. Verified live: correctly demoted a 9.0-heuristic job to 4.0 over an explicit 6+ years requirement.
- [x] Search expanded to 16 major metros + remote (willing to relocate)
- [x] Answer bank locked: no sponsorship needed, relocating OK, start July 1 2026 (why-leaving paragraph and EEO choices still TODO)
- [ ] Phase 2: prefill + review queue
- [ ] Phase 3: auto-submit adapters (Greenhouse → Lever → Ashby)
