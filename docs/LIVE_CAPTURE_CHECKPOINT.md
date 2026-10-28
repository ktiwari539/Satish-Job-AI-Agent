# Live export findings and full-JD continuation — 28 October 2026

Branch `fix/resume-radio-screening-20261026`; draft PR #2 records the exact latest SHA and CI result. No merge, deployment or real application was performed.

## Latest continuation: 0.6.2 and new real detail evidence

Two later exports were supplied at **13:41 IST on 28 October**. Both pass structural/timestamp validation; no real applicant qualification or application was attempted.

| Latest export | Rows | Valid posting URLs | Nonempty JDs | Correlated page-control inspections | Application forms exercised |
| --- | ---: | ---: | ---: | ---: | ---: |
| Naukri full posting, 13:41:36 IST | 1 | 1 | 1 (905 characters) | 1 (Apply) | 0 |
| Indeed search, 13:41:50 IST | 10 | 10 | 0 | 0 | 0 |

The Naukri posting identity and bundled inspection match exactly. It is useful live evidence for the previously broken current-job route. Its employer text includes a newline followed by a numeric rating/review suffix; the existing importer already normalizes that to the employer name before duplicate checks. The original export remains usable and **does not need to be captured again**. Its empty location field is not filled by guessing. Page-level input categories and an Apply control do not prove application-form entry, applicant eligibility, a selected resume, Review or permission to submit.

Version **0.6.2** makes both Naukri capture paths use the conservative importer cleanup: remove only a numeric review suffix and optional rating-only lines, preserving actual multi-line names. It also makes successful search downloads explicitly say **SEARCH listings only** with no full JD or form inspection. New current-tab exports include loaded extension version and informational counts/scope with `application_form_exercised=false`, `application_ready=false`, `submission_enabled=false`. Import qualification never trusts a client summary as readiness/approval.

The latest Indeed file is another search capture, not evidence that the dedicated-job extractor failed. Do not borrow its selected sidebar's JD: the sidebar can lag the search URL. Open one of its already observed `/viewjob?jk=...` links directly, then use the first export button. No batch grant or repeated Naukri export is required. The optional Indeed permission error remains unexplained because no access diagnostic was supplied.

Validation: 675 unit tests, 12 focused real-Chromium DOM simulations, popup/access/batch/Naukri/ATS smokes and all 34 Apps Script checks. Two new DOM cases cover current-tab/batch/search employer cleanup, with preserved genuine name lines. Unit regressions protect legacy-file dedupe and reject a forged client summary as qualification/submission authority. The full CI suite contains 47 synthetic DOM cases plus 3 installed-extension runtime checks, separately from real portal evidence; see draft PR #2 for the final CI status and latest SHA.

Nonprivate counts/source hashes for all four supplied exports are recorded in `docs/evidence/live-chrome-exports-20261028.json`. Raw attachments stay unchanged and outside Git. Verified private applicant facts and the active resume are unavailable in this workspace; do not fabricate them to score real jobs. Ordinary-Chrome form writing remains unimplemented/unverified.

## Prior continuation: 0.6.1 access/setup diagnostics

The user reported `Indeed batch access could not be enabled` and `No verified job links on this search page`. At that point no new export or native Chrome error was supplied. The 0.6.0 permission handler discarded the exception, so its message cannot identify the cause. Do not assert a policy restriction, broken login or lost user gesture without the browser reason. The second message means the batch had no verified posting source (or was invoked on a detail page); no job was opened or submitted. Naukri homepage recommendations previously exposed no valid links.

Version **0.6.1** opens optional Indeed setup in a normal extension tab, then requests access only when the user clicks **Enable Indeed access** there. This removes dependence on a toolbar popup surviving the native prompt. It checks the manifest Chrome actually loaded and shows version, access status, a specific reason code and sanitized browser error. Missing optional declarations, unavailable API, invalidated context, gesture and explicit policy errors have distinct guidance; unknown failures remain unknown. **Save access diagnostic** creates a local JSON with no tabs/job/account data. A delayed earlier access check cannot overwrite a newer request result. No new permission was added.

The popup now distinguishes an individual job from a search with no posting links and names the **first button** for current-job export. It does not guess links or retry the Naukri homepage batch. One-job export still needs no optional Indeed host grant. Existing login sessions are preserved.

Validation: 672 unit tests, existing DOM fixtures and Node suites, plus access-error/denial/privacy/race regression checks. Three new tests install the actual extension in isolated full Chromium to check native manifest/permission APIs, setup-tab wiring and a loaded-old-manifest mismatch; CI is the required result for these. Local full Chromium fails at its process-singleton Unix socket (`Operation not permitted`), independently of the extension. Local headless-shell DOM tests still run. These are not authenticated Mac portal or native permission-dialog acceptance. See PR #2 for final CI results.

## Earlier search-only evidence

The applicant installed Chrome Bridge **0.5.0**, confirmed by screenshot, after normal-Chrome login to both portals. Two real exports were inspected read-only:

| Export | Rows | Distinct supported posting URLs | Full JDs | Application-control inspections |
| --- | ---: | ---: | ---: | ---: |
| Indeed search, 10:28:58 IST | 10 | 10 | 0 | 0 |
| Naukri recommendations, 10:28:41 IST | 20 | 0 | 0 | 0 |

The Indeed file establishes current search-card capture and well-formed job keys, not live posting availability or eligibility. Each Naukri row has the same `/mnjuser/homepage` URL. The importer correctly rejects that file as `invalid_capture_job_identity`. Neither export contains the JD or form evidence needed for qualification/application preparation. No real applicant qualification was run with synthetic private facts.

Nonprivate counts/source hashes are saved in `docs/evidence/live-chrome-exports-20261028.json`. The uploaded files remain unchanged; raw job exports, account data and applicant facts are not committed.

## Root fix and version 0.6.0

The Naukri capture function accepted a non-posting link, and `new URL('', location.href)` could turn a missing href into the current homepage. This behavior explains how a homepage URL could be emitted as a job. The uploaded JSON does not reveal whether each live href was empty or explicitly pointed home; the fix rejects both.

Naukri now requires one **observed** HTTPS `job-listings-...` or `job-listings/...` URL from the card's href/data-url/data-href. It never synthesizes a posting from a title. Empty, non-job, ambiguous and duplicate links are excluded. A page with no valid postings exports safe counts-only diagnostics and instructs the user to open a full job, rather than emitting false jobs. The importer gives an explicit failure for an empty diagnostic capture.

Both portals now support an explicitly requested **Export full descriptions (up to 20)** batch. Indeed requires a separate optional site-access grant through **Enable Indeed full-description access**. Required permissions/required Naukri host access are unchanged; new optional host access is only `https://*.indeed.com/*`. Chrome grants site-level access, although the worker restricts its use to the exact job tabs this explicit batch opens. Current-tab Indeed export still works if that optional grant is declined.

The worker validates canonical job IDs, exact destination routes and matching title/company headers against each source card before accepting a JD. Naukri structured-data fallback additionally requires an explicit URL for the current posting; unrelated or identity-free JobPosting descriptions are ignored. Redirected/login, missing-description, header-mismatch, page-load failure and batch-budget outcomes are classified; they do not become qualified jobs. Every created tab is closed in `finally`. There is a 20-posting cap, bounded per-page probes and a two-minute batch budget (an already-started bounded probe may finish after that deadline). Remaining jobs are marked `batch_budget_exhausted`, not opened indefinitely. No Apply, Submit, login or security control is clicked.

## Validation and limits

672 unit tests include regressions for homepage/empty exports. Five additional real-Chromium synthetic DOM tests reproduce missing homepage links and verify observed, ambiguous, duplicate and explicit data-url behavior; the full browser suite has 45 cases. The new batch smoke suite uses simulated Chrome APIs to verify optional permission denial, current-tab independence, distinct IDs, redirect/header mismatch rejection, budget enforcement, cleanup and rejection of the actual homepage-shaped input. Existing popup, Naukri/ATS and 34 Apps Script checks remain in place. See PR #2 for actual passed checks and CI.

Those earlier search exports are actual live evidence; the later Naukri detail evidence is recorded above. Full-JD batches still require live Mac verification; browser fixtures and mocked Chrome APIs are separate evidence. Ordinary-Chrome field writing, resume/Review and approved submission are still unimplemented/unverified on this route. Existing LinkedIn form code and its open ten-real-form/verified Review gates remain separate.

## Exact next step

1. The Naukri full-posting export is accepted. Preserve it and the Chrome sessions; no repeat capture/login diagnostic is needed. Version 0.6.2 can be pulled/reloaded once to load the cleaner metadata and search-export status.
2. **Indeed only:** open an actual `/viewjob?jk=...` URL already present in its latest export directly in a tab, not just a search-sidebar selection. Click the extension → **Export current job / search**, the **first button**. Review/share that job JSON. No Apply click or optional batch access is required.
3. Optional batch investigation: **Set up Indeed batch access** → **Enable Indeed access** in the new tab. If setup still fails, save/share only the access diagnostic. It identifies the loaded version and Chrome reason; do not request passwords, repeat portal login, copy cookies or change managed-browser policies. This is separate from the immediate one-job export.
4. Qualification can run on the user's local machine using the existing verified profiles and `src/chrome_job_import.py`; configured Sheet pause/control rules still apply. In this workspace the next dependent work needs a real Indeed detail/control export and, for eligibility/resume/form verification, the verified local profile/resume or a sanctioned local report. Do not replace them with fixture facts. Current captures cannot authorize entering or submitting an application.

No passwords, OTPs, cookies, browser-profile transfer or new login diagnostics are required. Keep exact-job submission approval and release acceptance gates. Never retry manually applied LinkedIn job `4482859467`.

Prior [Chrome integration checkpoint](CHROME_BRIDGE_CHECKPOINT.md) and [extension guide](../browser-extension/naukri/README.md).
