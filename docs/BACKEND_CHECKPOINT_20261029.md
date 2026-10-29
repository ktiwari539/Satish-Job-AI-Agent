# Durable backend checkpoint — 29 October 2026

Branch `fix/resume-radio-screening-20261026`; draft PR #2 records the exact published SHA and CI. Nothing was merged, deployed, scheduled on the Mac or submitted to a real employer.

## Delivered

- A SQLite preparation queue sharing the existing application ledger: QUEUED, PREPARING, ELIGIBLE, PREPARED, NEEDS_INPUT, RETRY_WAIT, SKIPPED, SUBMISSION_RESERVED, SUBMISSION_UNCERTAIN and CONFIRMED. Job identities are canonicalized, tracking removed and ambiguous/account URLs rejected. Batch import is atomic and idempotent.
- Exclusive preparation leases with hashed tokens and stale-worker fencing. Expired preparation can recover at most three times; submission uncertainty never becomes a retry. Profile/resume/code changes revalidate preparation. Search snippets cannot downgrade full JDs or continually requeue the same completed work.
- Persistent pause/resume and cross-portal role dedupe. A blocked job advances to another job. The certification runner uses this queue by default and resumes pending discoveries even when the next search returns no new jobs. A changed/unavailable control source stops before form filling.
- PREPARED requires actual adapter evidence: exact job, exercised form, matching identity, accepted selected resume, inspected Review, Submit control and zero unknown/mismatched required fields. A bare READY_FOR_REVIEW string cannot pass. Preparation always keeps submission disabled.
- Atomic daily/window capacity reservations at the existing approved Submit guard, including concurrent cross-source duplicate prevention. Uncertain attempts hold capacity separately from confirmed successes. Confirmation replaces a hold without double counting. Additive schema upgrades retain legacy attempts/manual records. The approved pilot also refreshes source files, resume, Sheet controls, policy and eligibility immediately before reservation; changed/unavailable inputs stop the click.
- A local HTTP backend with authenticated job/status and pause/resume routes, plus a CLI. It binds only 127.0.0.1, creates a private random API token, rejects cross-origin/untrusted-host mutations, bounds JSON bodies and never logs credentials/body values. There are no HTTP submit, ready-state override or confirmation-write routes. Policy capacity shown by the API remains subject to current Sheet restrictions.
- Resume-derived role tenure now requires an explicit positive duration statement or label. A leadership summary followed by overall career years cannot become Customer Success tenure. Negative, compound and conflicting statements remain unknown; explicit lower bounds retain their `+`. Existing applicant-provided private facts are not overwritten.

## Validation and its limits

**743 unit tests** pass locally, including real SQLite concurrency, process-exit lease recovery, loopback HTTP requests, schema upgrade, midnight accounting, current-input checks, explicit role-tenure grounding and queue-to-certification integration. Shell/compile checks and existing Chrome/34 Apps Script simulations pass.

All **12 LinkedIn Chromium fixture tests** pass locally. The new integration exercises **ten distinct synthetic forms**, stops after four, reconstructs the queue, resumes six, verifies identity/resume/Review on all ten, then repeats discovery without repeating a preparation. **Zero Submit clicks.** Safe evidence: [backend queue fixture](evidence/backend-queue-fixture-20261029.json). Full CI has **56 synthetic browser cases and four isolated installed-extension checks** per browser matrix; see PR #2 for the final result. Synthetic IDs/applicants and routed local HTML are not live LinkedIn acceptance.

Current actual access: the Work runtime has the already-known resume and prior connected-Sheet readback. It does **not** have the Mac's authenticated browser, a local private profile file or a configured live Apps Script bridge. Do not request the resume, India authorization, old captures or login setup again. The saved Mac sessions and files must remain in place.

## One concrete Mac acceptance run

After pulling this branch, run from the existing project folder:

```bash
bash scripts/verify_linkedin_backend.sh
```

This is the new backend verification path, not the old certification/debug rounds. It reuses the project virtualenv, existing browser profile, private profile, resume vault and ledger; reads current Sheet controls; fixes scope to LinkedIn; considers at most ten jobs; never signs in, requests OTP or submits. It retains the existing worker lock. Report: `data/certification/backend-linkedin.json`. An absent bridge/private profile/session reports a blocker; it does not create applicant facts or restart login.

If the existing bridge has not been configured, a freshly exported, applicant-reviewed control workbook can be used for this manual non-submitting check with `--control-workbook /actual/path/current-controls.xlsx`. The old October snapshot was paused and has an unresolved answer; do not reuse it as current controls. No snapshot can authorize a submission. Do not share keys, passwords, cookies, CV contents or full private reports in chat/GitHub; only categorical blockers and acceptance counts are needed.

Local API, if wanted separately: `python3 src/agent_backend.py serve`. Read-only status: `python3 src/agent_backend.py status`. Pause/resume: the same command with `pause` or `resume`; a queue resume never overrides the Sheet's pause. API token stays in ignored `data/backend/token`. No remote hosting or Apps Script deployment was performed.

## Exact continuation

1. Inspect the new Mac report's queue states and per-job blockers. Classify actual LinkedIn entries; verify the selected resume and one genuinely new Review. Preserve manual exclusion `4482859467`.
2. Close only the concrete live failures that report reveals; original Issue #3 still needs ten genuinely unapplied real forms and one verified new Review. The ten synthetic forms do not close those gates.
3. Verify bridge connectivity and supported submission confirmation within release/approval gates. Daily standing-authorized production remains disabled/unimplemented. Then add other portals individually.

No additional information is needed to implement the backend. The remaining live check needs execution in the existing authenticated Mac environment; this Work session cannot operate that browser.
