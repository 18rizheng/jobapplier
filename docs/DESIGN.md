# Design

Agreed 2026-06-11. The original concept was: three resumes in, find 100 jobs paying $100k+, auto-apply via browser automation, run weekly. The critique below reshaped each step; the resulting architecture follows.

## Critique of the original concept

**Three static resumes → structured master profile.** Three PDFs are outputs, not inputs. A structured `profile.json` (work history, skills, canonical screening answers) is the source of truth; the three persona resumes (technical, analyst, general) are rendered from it, with light per-job tailoring of summary and skill ordering. The same data fills form fields — no parsing PDFs back into answers.

**"100 jobs over $100k" → fit-score threshold with salary estimation.** Most postings don't list salary; only pay-transparency states (CA, NY, CO, WA) reliably do. Filter on listed salary where present, estimate from title/level/location otherwise, flag unknowns rather than discarding. Volume quota replaced with a fit-score threshold: 30 well-matched applications beat 100 mediocre ones (spray-and-pray response rates run 1–3%).

**Full auto-submit → human review queue + two lanes.** Applications are one-shot: a bot answering a knockout question wrong (sponsorship, salary expectation) burns the company for 6–12 months, silently. The bot finds, scores, and prefills; the user approves batches in minutes. Execution splits:

- **Auto-submit lane**: hardcoded Playwright adapters for stable, no-login ATS forms — Greenhouse first, then Lever, Ashby.
- **Assisted lane**: Workday, iCIMS, Taleo, one-off portals — per-company accounts, email verification, CAPTCHAs. Claude in Chrome drives the user's real browser with the user watching, or queues a prefilled draft. No programmatic CAPTCHA defeat (unreliable + ToS evasion); CAPTCHA-blocked applications fail gracefully.

**Weekly → daily.** Applications in the first 24–72 hours of a posting get materially better response rates. Discovery polls daily (cheap API calls); review/apply happens in small daily or every-other-day batches.

## Pipeline stages

| Stage | Implementation |
|---|---|
| Discovery | `python-jobspy` (LinkedIn/Indeed/Glassdoor/ZipRecruiter/Google Jobs, anonymous, returns salary + posting age) + direct Greenhouse/Lever/Ashby public JSON pollers against a target-company list |
| Ingest + dedup | SQLite; hash on normalized company + title; every job seen is recorded so reruns never re-apply |
| Enrichment | 3-tier description extraction borrowed from ApplyPilot: JSON-LD → CSS selectors → LLM fallback |
| Scoring | Claude API: fit score per persona, salary filter/estimation, threshold gate |
| Review queue | Local dashboard; user approves / edits / rejects each batch |
| Apply (auto lane) | Playwright with persistent browser profile; per-ATS adapters |
| Apply (assisted lane) | Claude in Chrome; Workday navigation patterns referenced from proficiently-claude-skills |
| Tracker | SQLite outcomes + inbox scanning (concept from jobpilot's /scan-inbox) for replies and verification codes; feeds response rates by persona/source/score-band back into scoring |

## Resume tailoring rule (revised by Richard, 2026-06-11)

**Generative tailoring for every approved job.** The tailor rewrites the resume per
posting — new bullet text, recombined emphasis, job-matched vocabulary — it is NOT a
reorganizer. Safety comes from three layers instead of a reorder-only constraint:

1. **Grounding corpus** (`data/facts.md`): the single canonical source of permissible
   facts, compiled from the vetted resumes (and the claude.ai resume chat when provided).
   The generator may rephrase and recombine freely; every claim must trace to the corpus.
   Includes a hard NEVER-claim list (years of experience, degrees, certifications).
2. **Reviewer gate** (`pipeline/reviewer.py`): an independent adversarial pass that traces
   every generated resume bullet and cover-letter claim back to the corpus, checks the
   company name/title targeting, and verifies consistency with locked answers. Binary
   verdict; flagged packages cannot proceed.
3. **Human approval**: the review queue approves jobs before packaging, and the final
   package (including the generated resume) is inspectable before any submission.

Persona PDFs remain as fallback when generation fails. The exact resume file sent is
always stored in the application folder and database (interview-day consistency).

## Answer bank

Screening questions repeat (sponsorship, relocation, start date, "why us"). Canonical answers written once by the user, lightly adapted per job. Demographic/EEO questions are fixed user choices, never model-generated.

## Build order

1. **Discovery + scoring + tracker** — ranked daily list, applied to manually. Most of the value; proves the matcher before any automation exists.
2. **Prefill + answer bank** — bot drafts everything, user submits. Zero blast radius while draft quality improves.
3. **Auto-submit adapters** — Greenhouse → Lever → Ashby, only once prefill quality has earned it.
4. **Workday: assisted lane only.** Maintenance cost of full automation exceeds time saved.

## Lessons from prior art

- **AIHawk** (30k+ stars): all-in on LinkedIn Easy Apply automation → brittle, ban-prone, founder pivoted away. Validates API-first, ATS-direct, no logged-in platform automation.
- **ApplyPilot**: closest existing pipeline (discover → enrich → score → tailor → cover letter → apply) but no human review queue and no outcome tracker — exactly the two pieces this design adds.
- **jobpilot / proficiently-claude-skills**: reference implementations for inbox scanning and ATS navigation patterns respectively; not taken as dependencies.
