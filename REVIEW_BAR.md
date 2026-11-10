# REVIEW_BAR.md — polar-star-development

What "done" means for this repo. The ariadnes-clew-review skill checks every line. The repo is converged when all items are met or listed under Accepted gaps. The counsel (an AI review panel, `references/counsel.md` in the skill) recommends changes; Ian ratifies them by editing this file. The reviewer only proposes, via `reviews/bar-suggestions.md`.

Draft 2026-11-09 from review finding `polar-star:no-bar`. Not in force until Ian commits it.

## Must hold (S0 if broken)
- [ ] No private individual's name in any tracked file or public-mirror history: every test in `pipeline/test_no_private_names.py` passes
- [ ] The `restricted-name-gate` job in `publish.yml` runs on `[self-hosted, polar-star-gate]` with `POLAR_STAR_REQUIRE_RESTRICTED=1`, and `publish` needs it and checks out the sha it checked
- [ ] Deciding who is a private person fails closed: a missing dependency stops the build, never treats a person as an organization (`firm_profiles.is_person`)
- [ ] No secrets in tracked files; `.publish-deny` blocks `restricted/`, the donor file, `.env`, keys
- [ ] Only `.publish-authors` identities in published history; no AI-tool attribution lines (`commit-rules.yml` passes)
- [ ] No source that costs money or needs an identity-bearing account
- [ ] No link or reference to Arcturus

## Correctness (S1 if broken)
- [ ] Every number on the page traces to a `sources.csv` row with a primary-source URL
- [ ] A source past its `max_age_days` is shown as stale on the page, never served as current
- [ ] "Last posted" and "last checked" are separate: a source with nothing new shows when it was checked (`source_rows` test)
- [ ] Hand-checked help lines expire and hide when not reconfirmed
- [ ] "Current" officials filter on start date <= today (no officials-elect shown as serving)
- [ ] Donors are counted, never named; a lobbying-report person is named only with the lobbying tie

## Health (S2 if broken)
- [ ] `python pipeline/run_tests.py` passes on a clean checkout after `pip install -r requirements.txt`
- [ ] Every `sources.csv` source within `max_age_days`, or flagged on the page with the reason
- [ ] The weekly refresh succeeded within the last 8 days (`data/refresh_status.json`)
- [ ] README describes what the pipeline does now (run command, test runner, refresh)
- [ ] Every third-party action in `.github/workflows/` is pinned to a full commit sha

## Accepted gaps (not reported)
- Data contract export (`entities.jsonl`, `claims.jsonl`, `sources.jsonl`) and `clew-core` extraction: Phase 0 work, not yet started (2026-11-09)
- Strong-ID linking and two-EIN quarantine: hub concerns; apply here once the contract export exists (2026-11-09)
