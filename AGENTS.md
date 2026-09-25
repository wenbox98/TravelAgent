# Codex / coding-agent instructions

## Context
This repository currently builds a private, local travel research tool for its current owner. Public release and multi-user product work are deferred. Read `README.md`, the current task file and its referenced contracts before editing. User-facing text and implementation reports are in Simplified Chinese; code identifiers are English.

## Non-negotiable product rules
1. A vague travel request produces provisional high-level route options before a detailed questionnaire. Unknown budget, party size and transport stay unknown.
2. Xiaohongshu is a first-class research source. Manual pasted notes are a supplement, not a substitute for the automatic research acceptance gate.
3. Normal first-party login only. No cookie-copy instructions for end users, no password/SMS-code collection in this application, no captcha solving, fingerprint spoofing, proxy/account rotation or access-control bypass.
4. A model never gets cookies, xsec tokens, browser control endpoints or unrestricted upstream MCP tools. Only our business tools are exposed.
5. Grounded evidence, source completeness, time applicability and provenance must be preserved. Search metadata is not full article content.
6. No invented prices, availability, supplier API endpoints or successful test results. Missing data is explicitly unknown.
7. Budget and time constraints are evaluated by deterministic code. Locked choices cannot be silently changed.
8. External content storage and inference are controlled by the source policy. The current user explicitly selects PRIVATE_LOCAL_RESEARCH: limited researched detail text and derived data may be cached locally and supplied to the configured model for personal travel research. This usage mode does not assert author/platform permission; rights basis remains UNKNOWN. No public dataset, cross-user sharing, own-server upload or real-content Git commits. Keep authentication materials isolated in the dedicated browser profile.

## Work mode
- Inspect first; do not overwrite existing code blindly. Paths in task sheets are intended target paths, not claims that code already exists.
- Implement one task at a time. T00 and T01 may be completed in the first run; stop afterward with evidence.
- Dependency APIs evolve: pin real versions after checking compatibility; never invent a version, checksum or upstream release asset.
- `contracts/domain.schema.json`, `contracts/openapi.yaml`, and `contracts/database.sql` are initial contracts. If they conflict, report the conflict and change the contracts, docs and tests together in an explicit contract-change commit; do not silently pick an interpretation.
- Feature permissions and budget reservation occur before any upstream invocation. Tools with network side effects are never called from replayable presentation nodes.
- Tests use synthetic fixtures by default and deny external network access. Real-site tests require an explicit operator opt-in and must stop at login challenges/rate limits.
- Preserve a distinction among PASS, FAIL, SKIPPED and BLOCKED. SKIPPED is not PASS.
- Do not commit runtime data, authentication material, real scraped datasets, screenshots of logged-in accounts, `.env`, profiles or raw traces.
- Do not modify an unrelated learning repository. Do not publish a package, create a public repository, push branches or create a PR unless the user explicitly requests it.
- Standing user instruction: every TravelAgent development batch must commit and push its actual feature branch after checking the full unpushed commit range for secrets, profiles, real databases, raw sources/images, and sensitive diagnostics. Stage only an explicit file list; preserve unrelated changes and the three existing untracked T03 reports. At batch start, safely push any existing reviewed local commits before further development. At batch end, compare the full local HEAD with the remote branch SHA and return commit/compare links. Never force-push, automatically merge, or develop directly on master. Report PUSH_BLOCKED with the actual reason if synchronization fails; a failed G1 does not prevent pushing safe fixes and honest reports.

## Required task report
Write `reports/Txx-implementation.md`: intent; modified files and exact symbols; contract changes; commands actually executed and outputs; tests passed/failed/skipped; network calls (none unless opted in); pending manual work; risks; next task. Include `git diff --stat` if a Git repository exists. Never substitute planned tests for executed tests.

## Gates
See `docs/15-release-acceptance.md`. Offline development may continue when live validation is blocked, but do not label the Xiaohongshu integration or the application release as verified. Bundling an upstream project does not make its full tool surface acceptable.

## v1.1 Xiaohongshu PoC focus
- Before real-site work, read `docs/architecture/xhs-poc-analysis.md` and `docs/architecture/xhs-poc-design.md`.
- Prefer evidence-gap reduction, cache reuse, candidate deduplication and early stopping over adding more searches.
- `max_search_operations=3` and `max_feed_details=6` are PoC application budgets, never anti-ban or platform quota claims.
- A second request such as “只有5天，而且不想自驾” must reuse existing evidence first and only research the missing condition.
- Live work pauses on `NEED_LOGIN`, verification/challenge, explicit rate limit or access denial. Never bypass them.
- The PoC may start as CLI. Do not block data-path validation on Electron/UI work.
