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
.venv\Scripts\python run_discovery.py     # discover -> dedup -> score (heuristic + LLM)
.venv\Scripts\python review.py            # approve/reject scored jobs interactively
.venv\Scripts\python package.py           # generate tailored resume + cover letter + answers,
                                          # then the reviewer gate fabrication-checks everything
.venv\Scripts\python apply.py             # dry-run fill (Greenhouse) / assist checklists (rest)
.venv\Scripts\python apply.py --submit    # actually submit auto-lane applications
.venv\Scripts\python track.py stats       # response rates by persona and score band
```

Search terms, metros, ATS boards, and LLM settings live in [config/searches.json](config/searches.json). Register the daily 8am sweep once with [scripts/register_daily_task.ps1](scripts/register_daily_task.ps1).

### Status flow

`new -> scored -> queued (you approved) -> packaged -> reviewed | flagged -> applied`

## Status

- [x] Design (2026-06-11) — see [docs/DESIGN.md](docs/DESIGN.md)
- [x] Master profile parsed from three resumes (persona-tagged bullets, answer bank)
- [x] Phase 1: discovery (JobSpy + Greenhouse/Lever/Ashby pollers) → SQLite ingest/dedup → heuristic scoring → ranked list. Verified live: 60 postings, 51 new, real $100k+ matches ranked.
- [x] LLM scoring: Claude reads the full description vs the profile — fit 0–10, salary estimation for unlisted postings, knockout-risk detection. Backends: Anthropic SDK (`ANTHROPIC_API_KEY` in `.env`) or `claude` CLI fallback. Verified live: correctly demoted a 9.0-heuristic job to 4.0 over an explicit 6+ years requirement.
- [x] Search expanded to 16 major metros + remote (willing to relocate); 7 Greenhouse boards + Lever seeded
- [x] Answer bank locked: no sponsorship needed, relocating OK, start July 1 2026 (why-leaving paragraph and EEO choices still TODO)
- [x] Phase 2: review queue (`review.py`), generative tailoring grounded in `data/facts.md`, application packaging (`package.py`), reviewer fabrication gate (`pipeline/reviewer.py`)
- [x] Phase 3: Greenhouse Playwright adapter (dry-run default, `--submit` to send), assisted-lane checklists, outcome tracker (`track.py`), daily-sweep scheduler script
- [ ] Inbox scanning for responses/verification codes
- [ ] Lever/Ashby adapters; richer fact corpus from the claude.ai resume chat export
