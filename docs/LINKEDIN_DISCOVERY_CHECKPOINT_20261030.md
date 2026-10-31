# LinkedIn search checkpoint — 30 October 2026

**Next action superseded:** the applicant's Mac subsequently discovered seven complete jobs. Do not request another search inspection. See the [31 October form checkpoint](LINKEDIN_FORM_CHECKPOINT_20261031.md) for the exact-ID handoff correction and the actual non-submitting preparation command.

Branch `fix/resume-radio-screening-20261026`; PR #2 remains draft. The PR records the exact published SHA and CI result. No merge, deployment, schedule installation or real submission was performed.

## Actual Mac result

The applicant's backend run at `63ac2aa` loaded the existing control workbook successfully: enabled, REVIEW, eight reviewed answer rows, zero unresolved rows, submission disabled. LinkedIn returned `NO_VERIFIED_JOB_CARDS`: zero discoveries, JDs, forms, prepared jobs and submissions. No search DOM or post-navigation route was recorded. This proves a discovery blocker; it does **not** establish selector drift, a lost session, an empty inventory or a specific current LinkedIn layout. Safe counts: [actual run summary](evidence/linkedin-empty-search-20261030.json).

Do not request the workbook, CV, credentials, prior Naukri/Indeed exports or login setup again. The current workbook worked. The Work runtime cannot operate the authenticated Mac browser.

## Implemented root fixes

- The old extractor selected the first nonempty container family, even if those containers produced no jobs. Discovery now combines scoped layouts, explicit posting IDs and observed job links. Slugged links are canonicalized; conflicting IDs, untrusted origins, ambiguous metadata and detail-panel/sidebar content are rejected. A multi-job wrapper cannot suppress independently verified child links.
- The former roughly three-second card wait is now bounded polling for up to twelve seconds. Search origin, route and requested keyword context are checked before and after each DOM read. Post-search login/challenge/error/loading/no-results states take precedence over stale cards.
- Missing employer/location is retained as unresolved discovery metadata, then recovered from the exact verified posting before eligibility. The search location never becomes an applicant answer or guessed job location. Employer/title conflicts stop preparation. Repeated discovery preserves recovered employer/full JD and does not repeat completed preparation.
- Every search result includes fixed-schema structural diagnostics and a private atomic JSON file. These contain counts, booleans and categorical states, not page HTML, text, screenshots, credentials, cookies, entered answers or CV content. Unknown markup remains a blocker. Auth/unknown discovery failures do not drain that portal's pending queue; an explicit no-results page may resume previously verified pending work.
- Empty runs now distinguish discovery blocked, no jobs, no pending work and actual preparation. A locally paused queue without Sheet controls reports its pause before opening a browser.

## Measured verification

All **759 local unit tests** pass, including bounded classification, redirect races, identity conflicts, diagnostic privacy, private report permissions, metadata retention and queue pause. Nine new real-Chromium **synthetic** cases pass, covering mixed selectors, semantic ID-only cards, multiple links, delayed hydration beyond the old wait, no-results recommendations, hidden versus visible auth, post-search login with pending work preserved, and discovery through exact metadata recovery to verified Review. The latter exercises the real fixture form/resume/Review adapter and durable SQLite queue: one prepared, zero repeated preparations, zero Submit clicks. The existing 12 LinkedIn and seven multi-portal browser cases also pass locally. Compile, shell syntax, six Chrome/Apps Script simulation commands and whitespace checks pass. [Synthetic evidence](evidence/linkedin-discovery-fixtures-20261030.json).

The complete Python 3.9/3.12 and Playwright 1.55.0/1.64.1 matrix is required in PR #2. Browser tests use routed local HTML; isolated native extension tests are separate. None proves live LinkedIn acceptance. Extension stays 0.6.3; no reload is required for this change.

## Exact next step

Pull the branch in the existing Mac project, then run this **new read-only search inspector**:

```bash
git pull --ff-only origin fix/resume-radio-screening-20261026
bash scripts/inspect_linkedin_search.sh
```

It uses the existing project environment and saved agent browser profile, shares the worker lock, opens only the requested search and records evidence before closing. It never signs in, reads applicant files/Sheet controls, opens an application form or submits. No workbook argument is needed. Share its small terminal JSON, or `data/certification/linkedin-discovery-latest.json`. If the worker is already running, wait for that run to finish; do not run overlapping browser processes.

Continuation by result:

- `DISCOVERED`: the code path now reads verified job identities. Continue the non-submitting backend acceptance with the same working workbook, then inspect exact JD, eligibility and form/resume/Review outcomes.
- `SEARCH_LOGIN_REQUIRED` / `SEARCH_CHALLENGE`: preserve the saved profile and classify the visible session state. Do not restart Google-login retries or bypass security checks.
- `SEARCH_LOADING_TIMEOUT`, `SEARCH_CARD_METADATA_INCOMPLETE`, `SEARCH_IDENTITY_CONFLICT`, `SEARCH_MARKUP_UNSUPPORTED` or probe/route errors: use recorded structural counters to select the next narrow investigation. A sanitized job-card structure from that specific page may then be necessary; do not infer its layout from fixtures.
- `SEARCH_NO_RESULTS`: this exact search explicitly has no results. Review filters/inventory before another form run.

Original Issue #3 remains open: ten genuinely unapplied real forms, one new Review with selected resume and all release gates verified, and evidence-based classifications of the historical six jobs. Keep manual exclusion `4482859467`. Daily production and further portal adapters remain separate gates. No job-specific submission approval was given in this continuation.
