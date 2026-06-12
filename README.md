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

## Status

Design phase complete (2026-06-11). Next milestone: parse resumes into master profile, JobSpy discovery + scoring producing a ranked daily list.
