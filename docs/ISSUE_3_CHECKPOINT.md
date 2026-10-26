# Issue #3 checkpoint — 26 October 2026

Branch: `fix/resume-radio-screening-20261026`. PR #2 stays draft/unmerged.
Baseline inspected: `4b73e4373b42ae4e3cc462e1ddce64bceb6851bc` (548 unit tests).
Use `git rev-parse HEAD` for the current checkpoint SHA; final SHA and CI URLs are in PR #2.

## Implemented

- Easy Apply discovery requests `f_AL=true`; CTA identity is checked rather than inferred from the shared `jobs-apply-button` class. Generic Apply/company-site buttons are external, never Easy Apply. Recommendation-card CTAs are excluded.
- Exact-job missing-entry reports now distinguish external, applied, unavailable, auth/page mismatch, loading and selector/layout failure. Counts/booleans only; each blocker capture gets its own file. Queue summaries retain per-job classifications, resume state, unknown-field counts and report paths.
- Resume evidence compares exact displayed names inside the application, supports hidden native selection radios and final Review document cards, and verifies vault hash/manifest provenance before accepting its original-name alias. A file input alone remains unconfirmed. This proves UI attachment identity and local provenance, not a server-side byte-for-byte document digest.
- Review stays distinct from Submit readiness. Certification requires the exact job route, matching name/email/phone, a current matching resume selection/document and the final enabled Submit resolver. Debug never invokes a submitter.
- LinkedIn live approval must identify one exact job URL. The production caller must provide a durable submission guard. A transactional reservation is committed before the click and survives failures, timeouts or process exit. Confirmed writes are idempotent. Applied controls must belong to the current job panel; recommendation/sidebar badges cannot confirm another job. Preexisting success UI blocks a new click, and post-click confirmation cannot cross to a different job route. A reserved uncertain attempt blocks automatic retries; reconcile the exact portal job before any deliberate local database repair.
- Confirmed Applied history persists beyond the 24-hour diagnostic cooldown. Job `4482859467` is also an explicit user-confirmed exclusion from Issue #3, protected even with a fresh database. Other blocked/external jobs use a bounded 24-hour QA retry history; that history is not cross-portal production dedupe.
- New bounded certification runner collects the six historical job diagnoses plus fresh discovery rounds, saves one measured report and exits nonzero until ten distinct forms and at least one fully verified Review are recorded.

## Verification scope

Current local verification (including missing-runtime preflight, cooldown recovery and launcher checks): **580 unit tests passed**, **11 real Chromium fixture tests passed** (107.4 seconds), compile/shell/extension syntax and smoke checks passed, and offline discovery dry-run passed. The synthetic queue report is committed at `docs/evidence/fixture-acceptance-20261026.json`.

Unit tests and synthetic Chromium integration are separate CI jobs. The browser suite routes every request to synthetic HTML, uses a synthetic applicant, invokes the real parser/filler/navigation/queue, and never contacts LinkedIn/ATS services. Its ten-job queue has nine verified Reviews, one truthful unknown-question blocker, zero Submit clicks and no repeated form openings on the next queue run.

A separate synthetic approved-submission test executes one local fixture button click, renders a local success response, writes confirmation once and rejects a repeated reservation. That test is not a real application; the debug queue itself retains zero Submit clicks.

This workspace has **no** authenticated Mac LinkedIn profile, `data/private_profile.json`, local jobs ledger or resume vault. No actual LinkedIn or ATS application was opened/submitted here. Live release acceptance is **pending**, not passed by fixture results. The latest Mac attempt failed at browser-runtime import: **zero job pages were inspected**. The earlier summary's six `distinct_jobs_checked` were six considered URLs, not browser checks; the corrected report separates those counts.

## Historical live failures still requiring current evidence

| Job ID | Existing evidence | Current classification |
| --- | --- | --- |
| 4455142560 | NO_EASY_APPLY_ENTRY | Pending authenticated run |
| 4470305150 | NO_EASY_APPLY_ENTRY | Pending authenticated run |
| 4482617347 | NO_EASY_APPLY_ENTRY | Pending authenticated run |
| 4467551783 | NO_EASY_APPLY_ENTRY | Pending authenticated run |
| 4458178908 | NO_EASY_APPLY_ENTRY | Pending authenticated run |
| 4477985661 | One unknown required field | Question/options and verified applicant answer pending |

Do not infer that the first five are external solely from the old error. Do not invent the last screening answer.

## Exact next step on the Mac

After pulling this branch, use the existing authenticated `browser-profile`, private profile, resume vault and jobs database:

```bash
bash scripts/certify_linkedin.sh --setup --include-issue3-jobs --rounds 3
```

The launcher reuses `.venv/bin/python` when available. `--setup` creates that environment only if missing, installs Playwright only if it cannot be imported, and ensures its matching Chromium is installed. It preserves the saved browser profile, private applicant files, resume vault and jobs ledger. Omit `--setup` on later runs; `JOB_AGENT_PYTHON` can select another already configured interpreter.

The Mac run reported `BrowserRuntimeUnavailable` before any job page was inspected: the active interpreter could not import Playwright. Certification now checks that once before jobs, reports the environment blocker clearly, preserves discovery errors, and stops instead of repeating six failures. Old missing-runtime history entries are automatically ignored as cooldowns; real Applied protections remain intact. `distinct_jobs_considered` and `distinct_jobs_checked` are now separate, so unopened candidates do not count as live checks.

This command never submits. It checks the six historical jobs, then performs at most three discovery rounds, 20 candidates and five form inspections per round. It advances automatically after blocked jobs. The real-world count may be below ten if the search returns too few new jobs or all remaining jobs are on cooldown; the report must then stay pending. Adjust the query/location to expand the pool instead of deleting dedupe state.

Share only `data/certification/latest.json` and the referenced `data/agent_runs/*.blocker.json` files (safe structural evidence). Do not share browser profiles, cookies, credentials, private applicant JSON, resume files or complete page HTML. The report records the exact final resume evidence, identity gate, Submit-resolver readiness and per-job outcomes. A name-only/manual screenshot can be shared after redacting contact details and document filenames if the DOM evidence is insufficient.

If job 4477985661 still needs a truthful answer, inspect it locally once:

```bash
python3 src/job_agent_cli.py --portal linkedin --job-url 'https://www.linkedin.com/jobs/view/4477985661/' --debug-easy-apply-only --debug-interactive
```

Enter only the applicant-verified answer in the local terminal. The existing interactive recovery stores it in the private profile and rechecks the page without submitting. If the field still cannot be resolved, provide only its question/options and the verified fact needed for a reusable resolver.

## External ATS support limits

- Greenhouse/Lever public discovery already exists. Standard native text/select/file forms are inspected and filled in local fixtures.
- External links can be followed by the existing application adapter; supported URL/provider inspection remains bounded.
- Custom widgets, account/OTP/CAPTCHA flows, iframes and Workday/Rippling-specific multi-step layouts have not received new live certification. Generic file upload does not prove ATS acceptance of the resume. Such flows must block when identity/resume/required answers cannot be verified.
- No real external ATS submission is certified or approved by this work. Per-job approval is still required separately.

## Resume next session without re-investigation

Read this file and PR #2's latest checkpoint, fetch the branch and inspect the existing CI jobs. Start with the single Mac certification report above; repair only failures established by its evidence. Keep Issue #3 open until the six historical classifications, ten real unapplied-job tests and one verified live Review are supplied. Do not retest job 4482859467, submit, merge or deploy.
