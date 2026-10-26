# Satish Job AI Agent — multi-portal checkpoint

Branch: `fix/resume-radio-screening-20261026`. PR #2 remains draft/unmerged. Use `git rev-parse HEAD` or the PR description for the latest SHA.

## Objective and current scope

The objective remains an independent agent that discovers suitable roles across job portals, cross-checks the applicant's verified information, fills supported applications, and submits only through a certified, explicitly approved path. LinkedIn certification is one acceptance gate within that objective. The existing requirement for explicit approval of each real job submission remains in force. No real applications were submitted in this work.

## Latest Mac blocker

The Mac successfully installed Playwright, but Chromium failed before opening a job. The previous setup incorrectly used a fixture-only Playwright 1.51 pin, installed Chromium build 1161 and garbage-collected previously cached build 1187. This downgrade is confirmed by the user's installer output; it is not yet proof of the browser launch failure's cause.

Setup now uses a separate runtime dependency floor (`config/browser_requirements.txt`, Playwright >=1.55), lets pip choose a version compatible with the selected Python, and sets `PLAYWRIGHT_SKIP_BROWSER_GC=1`. Existing supported runtimes are preserved. Browser and driver versions must match; a saved profile made by a newer Chromium is blocked before a known downgrade is attempted. No browser profile, cookies, private facts, resume or ledger is deleted/reset.

Launch failure evidence now contains safe package/browser/profile version numbers, architecture, startup phase, whitelisted crash/exit signals and specific permission/profile-lock/timeout/dependency categories. Unknown persistent-profile launch errors trigger one bounded blank-browser probe without opening the saved profile or visiting any portal. A successful blank probe does not prove the saved profile or authentication works.

## Implemented across portals

- New `certify_portals.py` and environment-aware launcher use the existing normalized job model, role/skill/experience scoring, eligibility and application ledger.
- Indeed discovery reads fixture-tested cards; canonicalization preserves `jk`/`vjk` identity instead of merging all `/viewjob` URLs. Known LinkedIn job IDs are recovered even when card attributes are missing. ATS identity query parameters survive tracking removal.
- Full JD extraction reads visible matching nodes, including non-first DOM copies; the broader runner never substitutes page/footer/login text for a JD.
- Qualification and private-profile total experience are cross-checked; contradictory or missing identity facts stop before browser interaction. Search location is not confused with applicant home city.
- Shared preparation fills verified native application forms for Naukri/Indeed/Greenhouse/Lever and retains LinkedIn's dedicated wizard path. Readiness requires exact job route, identity readback, selected/accepted resume evidence and the final Submit control. A file input alone does not pass.
- Native one-click Apply controls and custom/unknown entry flows are not clicked as navigation. Unsupported adapters are reported truthfully. Unknown required answers stop that job and the queue continues.
- Same-role cross-postings are suppressed within a preparation batch. Confirmed submissions and uncertain reserved attempts remain protected by the existing persistent ledger.
- A separate persistent 24-hour preparation cooldown skips unchanged blocked/ready forms on later runs. An opaque revision covers verified facts, resume bytes, job details, Playwright version and relevant code; changes allow an immediate recheck. Preparation never creates a submitted-application record, and global browser failures never create a cooldown.
- A browser disconnect is a global blocker, not six job rejections; completed per-job evidence is retained. Public feed failures are isolated per board/site and portal.

## Evidence and remaining work

Unit checks cover setup preservation, version/downgrade prevention, crash diagnostic privacy, source identity, fact conflicts, global-vs-job failure recovery, duplicate suppression and partial evidence retention. Chromium fixtures cover the original LinkedIn suite plus visible native forms, unknown answers, one-click safeguards and a real three-portal orchestration over synthetic pages.

Local validation: 613 unit tests; 16 Chromium fixture tests with Playwright 1.55.0 / Chromium 140; extension syntax/read-only smoke checks; offline qualification smoke; Python compilation and shell syntax. A real Linux headless persistent-profile startup also passed against a new temporary profile with zero portal visits. This does not verify Mac startup or any authenticated account. CI checks Python 3.9/3.12 and both Playwright 1.55.0/1.64.1; see the PR for the final run results and commit.

Measured synthetic multi-portal run: four postings discovered; two distinct verified Reviews; one unknown-answer blocker; one cross-portal duplicate suppressed; zero Submit clicks. Native form fixtures also pass for Greenhouse and Lever. These are local synthetic pages and do not certify real account behavior or unseen ATS widgets.

Saved reproducible evidence: `docs/evidence/multi-portal-fixtures-20261026.json`. The browser CI artifacts also contain the original ten-job LinkedIn fixture report. One original fixture separately exercises an explicitly approved simulated submission on a local synthetic page; no real application is sent.

Remaining live gates: repair/verify Mac startup, classify the six historical Issue #3 jobs, exercise at least ten distinct real unapplied LinkedIn jobs with one fully verified Review, and independently certify Naukri/Indeed/external ATS entry, Review, resume and confirmation layouts. Workday and other registered portals still need adapters. Do not mark the agent universal/perfect based on fixtures. Do not retest manually applied job 4482859467.

## Exact next step on the Mac

After pulling the branch, run once:

```bash
bash scripts/certify_portals.sh --setup --portals linkedin,naukri,indeed --max-jobs 10
```

This repairs the local runtime floor, preserves browser caches and runs preparation without submitting. It uses existing local facts/profile/resume/ledger. Share only `data/certification/portals.json` and its referenced structural blocker reports. A browser failure now includes safe launch evidence; a profile fact conflict includes field names only. Never share raw browser stderr, cookies, credentials, browser profile directories, private applicant JSON or CV contents.

Keep the older `certify_linkedin.sh --include-issue3-jobs --rounds 3` path for the separate exact historical LinkedIn acceptance run after the runtime works. See `PORTAL_MATRIX.md` for current supported/unverified boundaries and `docs/ISSUE_3_CHECKPOINT.md` for the prior Issue #3 context.
