# Live export findings and full-JD continuation — 28 October 2026

Branch `fix/resume-radio-screening-20261026`; draft PR #2 records the exact latest SHA and CI result. No merge, deployment or real application was performed.

## Latest continuation: durable local backend implemented

See [backend checkpoint](BACKEND_CHECKPOINT_20261029.md) for the delivered persistent queue, local HTTP API, pause/resume, recovery, capacity reservations, current-input submit guard and role-tenure grounding fix. **743 unit tests** and all **12 local LinkedIn browser fixture cases** passed. The new fixture prepared ten distinct synthetic forms across a restart (4 + 6) with zero Submit clicks and no repeated preparation. This is not actual LinkedIn certification. The single new Mac check is `bash scripts/verify_linkedin_backend.sh`; it reuses existing files/sessions and reports to `data/certification/backend-linkedin.json` without login or submission. Do not repeat old diagnostics or request already supplied applicant facts. The Work runtime still cannot control the authenticated Mac browser or verify its live bridge configuration. PR #2 contains final SHA/CI.

## Latest continuation: portal selection and operating model — 29 October

The user requested a complete operating decision for India/overseas/remote providers and daily applications after one setup, using Script Properties credentials, reviewed answers, filters and a configured cap. This is now the target authorization model; it does not remove current technical or service-access gates. See [the operating plan](OPERATING_PLAN_20261029.md). LinkedIn remains the first user-facing workflow, using permitted/manual or authorized integration steps because its official policy prohibits third-party website automation. Indeed also prohibits third-party application bots. Public employer feeds provide a separate supported discovery route; submission permission is not inferred from public-read access.

Found a real schedule-wiring defect: `run_review_window.sh` called the single-submit CLI without approval and exited before review work. It now enters a fixed non-submitting worker with current Sheet controls, configured public Greenhouse/Lever sources, no automatic login/interactive OTP, bounded job counts, an exec-preserved kernel lock and project-Python reuse. Empty employer sources or browser-portal scheduling settings produce explicit configuration blockers. The installer serializes plist XML and stores allowlisted settings; script changes now trigger CI. This has not been installed on the Mac. No schedule, live control value, credential, resume, private profile, ledger or submission gate was changed.

Earlier accepted captures and India authorization remain valid historical evidence. No repeat exports, resume upload or login setup is requested. Work-location investigation for old captures is retained; it is not the sole blocker to a multi-portal autonomous agent. The deployed credential/control bridge, real form/resume acceptance, reliable unattended permitted integrations and production standing-authorization execution are still unverified or unfinished. Do not claim the full agent is operational from scheduler tests.

Local validation: 697 unit tests, Python compilation, shell syntax and whitespace checks passed. Ten new scheduling regressions cover current-control/review routing, unsupported and empty-source blocking, bounded arguments, project interpreter reuse, safe plist serialization, overlap and actual exec/crash lock recovery. No browser fixture was added or reclassified as live evidence.

## Latest continuation: authorized REVIEW preparation — 29 October

The applicant explicitly reviewed the previously unresolved authorization fact and enabled REVIEW preparation, requesting profile-matched India, overseas and remote roles. The connected Sheet was read with exact metadata/ranges before editing, then read back. Config now enables REVIEW and worldwide discovery; Question_Bank has eight reviewed automatic answers and no unresolved rows. The older dropdown offered VALIDATION/AUTO while code supports VALIDATION/REVIEW/LIVE; it was aligned to those supported modes. A separate AUTHORIZED choice records work authorization without inferring a sponsorship exemption. Existing overseas sponsorship requirements remain in force. Only intended values/validation changed; original cell formats/wrapping were preserved by API comparison. Native visual rendering was not performed. No Sheet ID, financial/contact answers or credentials are committed.

Code now carries a current reviewed authorization decision to both qualification and plain India-specific form questions. Config alone, stale/disabled/ambiguous answers and conflicting local facts cannot create authorization. Full question matching excludes sponsorship, citizenship, permanence, negation and other jurisdictions. Temporary Sheet facts stay in memory and are not persisted through interactive answer learning. REVIEW cannot enable submission even when read from the live bridge.

Worldwide discovery is a search preference, not universal work authorization. Missing/generic work locations are explicitly review-required instead of mislabeled overseas. Relocation assistance alone does not establish visa sponsorship, generic remote does not mean worldwide, and India is matched as a whole location token rather than as a substring of Indiana/Indianapolis. Import reports retain categorical eligibility reasons.

The existing resume named by Config was found through connected Drive, downloaded privately, structurally read and imported into the local integrity-checked resume store. Its contact fields plus the reviewed Sheet facts were used transiently for the existing consistency checks. No fixture identity or fabricated screening answer was used. This proves local source/file availability, not that a portal accepted or selected the resume. The deployed Apps Script bridge and the applicant's Mac browser remain separate, unverified access paths here. Do not request the resume again without consulting the existing named Drive source.

Read-only evaluation of the two accepted detail captures at **07:48 IST on 29 October**, within the capture freshness window:

| Portal | Full JDs | Match score | JD skill evidence | Result | Forms opened / submissions |
| --- | ---: | ---: | ---: | --- | ---: |
| Naukri | 1 | 78 | 2 distinct skills | Review required: work location absent; insufficient JD skill evidence | 0 / 0 |
| Indeed | 1 | 92 | 9 distinct skills | Review required: work location absent | 0 / 0 |

These are real saved job-data evaluations with a connected Sheet readback and sourced applicant fields, **not live-browser form exercises**. The duplicate check used an empty isolated ledger, so it does not certify the applicant's historical application status. Raw captures, CV, private source IDs and private reports remain outside Git. Safe evidence is in `docs/evidence/review-preparation-20261029.json`.

Local validation: **687 unit tests** and compile passed. Twelve new unit cases cover authorization propagation/conflicts/scope/retention, REVIEW submission denial, missing-location reporting, Indiana, remote limits and relocation-vs-sponsorship. The existing **55 synthetic DOM cases plus four isolated installed-extension runtime checks** remain separate from actual live acceptance; PR #2 records the final CI result. Extension remains **0.6.3**; no reload is required for these Python-only changes.

Exact next step: recover work-location evidence from the exact-job full-description layout and add a representative regression, preserving the accepted exports unchanged. Naukri additionally needs sufficient job-specific skill evidence before qualification. Then continue the ordinary-Chrome form adapter and verify a non-submitting form/resume/Review using the existing authenticated Mac sessions. Work runtime has no control over those Mac sessions. Maintain per-job submission approval, original LinkedIn release gates and the manual-application exclusion. No new login/setup or repeat export is required for the existing capture investigation.

The sections below are historical and do not override the new REVIEW authorization/readback.

## Prior continuation: actual Indeed detail accepted; live control gate checked

The user supplied a **0.6.3 Indeed detail export at 17:22:56 IST on 28 October**. Structural/timestamp validation and exact-job inspection correlation passed. It contains **one job, a 7,147-character description and one Apply-control inspection**, with `reason_code=job_captured`, `layout_variant=viewjob_vj` and one extraction attempt. The canonical job identity matches its earlier search row. The Apply target is an Indeed link with `smartapply.indeed.com` origin; this is not proof that an application form was opened. No challenge was detected. Location is empty and is not guessed.

This is real user-exported Chrome evidence after the public-HTML replay and fixture checks. It establishes the current-job extraction fix for this one page, not applicant eligibility, selected resume, Review, authenticated-session ownership or submission readiness. No real qualification/application was run. The raw file remains unchanged and outside Git; nonprivate counts/hash are appended to `docs/evidence/live-chrome-exports-20261028.json`.

**Both Naukri and Indeed now have accepted job-detail/control exports. Do not request either capture again, repeat login diagnostics, or require a new extension version just to continue.** Chrome Bridge stays 0.6.3 and application code stays at `54124c4abad914f5849597af92a13f150c44f3db`. Its complete CI passed: https://github.com/ktiwari539/Satish-Job-AI-Agent/actions/runs/40679271387 — 675 unit tests on Python 3.9/3.12 and 55 synthetic DOM + 4 isolated native-extension checks on both browser versions. This continuation changes checkpoint/evidence documentation only; no code or new tests are needed.

The actual connected control Sheet was then read **without edits**, using metadata-confirmed bounded Config/Question_Bank ranges. It is still **paused**: `Config!B4=FALSE`, `Config!B5=VALIDATION`. `Question_Bank` row **8** has unresolved India work authorization, no approved answer and automatic answering disabled. This is a fresh live read, not an assumption based on the older workbook snapshot. No private source ID, financial/applicant answers or credential data are committed; safe gate states are in `docs/evidence/control-gate-20261028.json`.

The Work runtime has no verified private profile or resume file. Leave qualification/form preparation stopped under the current pause; do not use the public profile's older India-authorized flag or invent an answer. The exact next step is user review of the work-authorization row before any explicit change to REVIEW/preparation controls, followed by access to the existing verified local profile/resume or a sanctioned local report. No Sheet/control values were changed. Ordinary-Chrome form writing, resume/Review and per-job-approved submission remain outstanding; original LinkedIn live acceptance gates stay open.

## Prior continuation: 0.6.3 Indeed layout root fix

After opening a dedicated Indeed posting, the user reported **No complete job found**. Do not ask them to repeat the same old-version export. Investigation of actual public HTML for an ID already in their export found that the old description/header/company selectors are absent. The new layout uses h5 `data-testid="vj-job-title"`, company metadata's `/cmp/` link and `.simple-job-description-html` scoped inside `viewjob-job-content`.

Version **0.6.3** reads this observed structure, preserving legacy selectors. Replaying the actual public HTML in isolated Chromium reproduced **0 jobs with the prior extractor**, then **1 job with a 7,147-character description** using the fix. Employer and application-inspection identity matched the supplied search posting. Page scripts and network resources were blocked in replay. This is actual-public-markup evidence, **not a signed-in Mac run, qualification or application-form exercise**. Safe counts/source hash are in `docs/evidence/indeed-public-layout-20261028.json`; raw HTML/full third-party JD is not committed.

The extractor now allows four bounded reads separated by 400 ms for hydration, rechecking exact identity each time. It never borrows selected search-panel/account text. An additional structured-data fallback accepts only one explicit current-job URL with consistent title/company; the observed page's JSON-LD lacks a URL and is ignored. Changed jobs, challenges, unavailable jobs, missing/short components, unsupported routes and ambiguous/mismatched metadata get structural reason codes.

The old generic failure now downloads **indeed-jobs-diagnostics-<timestamp>.json** with zero jobs, fixed reason codes, counts/booleans, route category and loaded version. It includes no body/title text, arbitrary DOM attributes, URLs/tokens or entered values. This is diagnostic evidence, not a job or readiness assertion. Current-job export still requires no optional Indeed host grant and performs no Apply/login interaction.

Local validation: 675 unit tests, 20 focused Chromium DOM simulations and all existing extension/34 Apps Script checks passed. Eight new DOM regressions cover the observed h5/component layout, unrelated component exclusion, delayed hydration, job changes, exact structured identity, conflicting/ambiguous metadata, challenges/routes and short descriptions. The complete CI suite now has **55 synthetic DOM cases plus 4 isolated installed-extension runtime checks**. The new native check verifies asynchronous file/Promise results through Chrome's scripting API on an isolated routed fixture, without granting Indeed access; local full Chromium remains socket-blocked, so CI is required for runtime checks. PR #2 records final CI and latest SHA. Authenticated Mac Indeed capture and real form/resume/Review gates remain open.

## Prior continuation: 0.6.2 and real Naukri detail evidence

Two later exports were supplied at **13:41 IST on 28 October**. Both pass structural/timestamp validation; no real applicant qualification or application was attempted.

| Latest export | Rows | Valid posting URLs | Nonempty JDs | Correlated page-control inspections | Application forms exercised |
| --- | ---: | ---: | ---: | ---: | ---: |
| Naukri full posting, 13:41:36 IST | 1 | 1 | 1 (905 characters) | 1 (Apply) | 0 |
| Indeed search, 13:41:50 IST | 10 | 10 | 0 | 0 | 0 |

The Naukri posting identity and bundled inspection match exactly. It is useful live evidence for the previously broken current-job route. Its employer text includes a newline followed by a numeric rating/review suffix; the existing importer already normalizes that to the employer name before duplicate checks. The original export remains usable and **does not need to be captured again**. Its empty location field is not filled by guessing. Page-level input categories and an Apply control do not prove application-form entry, applicant eligibility, a selected resume, Review or permission to submit.

Version **0.6.2** makes both Naukri capture paths use the conservative importer cleanup: remove only a numeric review suffix and optional rating-only lines, preserving actual multi-line names. It also makes successful search downloads explicitly say **SEARCH listings only** with no full JD or form inspection. New current-tab exports include loaded extension version and informational counts/scope with `application_form_exercised=false`, `application_ready=false`, `submission_enabled=false`. Import qualification never trusts a client summary as readiness/approval.

At that point the latest Indeed file was another search capture; the subsequent dedicated-page failure is investigated above. Do not borrow a selected sidebar's JD: the sidebar can lag the search URL. No batch grant or repeated Naukri export is required. The optional Indeed permission error remains unexplained because no access diagnostic was supplied.

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

1. Preserve the two accepted job-detail exports and Chrome sessions. No new capture, login, extension reload or setup diagnostic is needed.
2. Honor the newly reviewed controls. Do not ask again for the already-confirmed authorization or REVIEW permission. Refresh source reads when continuing; snapshots cannot authorize submissions.
3. Use the existing Sheet-named Drive resume and reviewed facts; private local source files are under ignored `data/private/` when retained. Do not commit these or substitute fixture facts. Restore them from their known connected sources if the runtime is reset.
4. Recover exact-job work-location evidence and continue the ordinary-Chrome form adapter. An Apply link is not an application form; its field writer is still unimplemented/unverified. A future real form/resume/Review check needs the applicant's authenticated Mac browser, and every submission needs exact-job approval. Optional Indeed batch-access diagnosis is separate and not the immediate blocker.

No passwords, OTPs, cookies, browser-profile transfer or new login diagnostics are required. Keep exact-job submission approval and release acceptance gates. Never retry manually applied LinkedIn job `4482859467`.

Prior [Chrome integration checkpoint](CHROME_BRIDGE_CHECKPOINT.md) and [extension guide](../browser-extension/naukri/README.md).
