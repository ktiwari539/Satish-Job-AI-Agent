# Satish Job Agent — ordinary Chrome bridge

Version **0.6.1** supports user-invoked, read-only Naukri and Indeed job capture and bounded full-description batches in the Chrome session where the applicant is already signed in. The directory remains `browser-extension/naukri` so existing installations can be reloaded. The popup shows the manifest version Chrome actually loaded.

Actual 0.5.0 exports contained ten Indeed search IDs and twenty invalid Naukri homepage URLs, with no JDs/forms. The Naukri identity bug is fixed: empty/non-posting links are excluded, and a page with no verified job links exports counts-only diagnostics. Open a full posting rather than repeating the homepage recommendation export. See [live findings](../../docs/LIVE_CAPTURE_CHECKPOINT.md).

The user has confirmed ordinary-Chrome login to both portals. Do not repeat the rejected Playwright Google login. This extension does not transfer browser sessions, read credentials/cookies, fill fields, click Apply/Submit or certify an application.

## Install or reload once

1. From the repository, pull `fix/resume-radio-screening-20261026`.
2. In the already signed-in ordinary Chrome, open `chrome://extensions`.
3. Enable **Developer mode** → **Load unpacked** → select `Satish-Job-AI-Agent/browser-extension/naukri`.
4. If installed already, use **Reload**. Verify **Satish Job Agent - Chrome Bridge**, version **0.6.1**.
5. Pin the extension using Chrome's Extensions menu.

[Chrome's official load/reload instructions](https://developer.chrome.com/docs/extensions/get-started/tutorial/hello-world#load-unpacked).

## One live job export from each portal

1. Open an individual Naukri job description (`job-listings-...`). On Indeed open the full job in its own tab (`/viewjob?jk=...`), rather than only selecting a search sidebar.
2. Click the extension → **Export current job / search**. No Apply click is needed.
3. A dedicated job export includes the job title, employer, location, full visible JD, canonical job URL and read-only application-control inspection. A changed job between reads aborts the export.
4. It downloads `naukri-jobs-<timestamp>.json` or `indeed-jobs-<timestamp>.json`. Review these two files before sharing them for live adapter verification. No browser profile, passwords or cookies are needed.

Search-page exports retain search-card metadata only, never a full JD from a potentially stale selected panel. Missing/unsupported JD layouts do not become qualified jobs. Indeed exports retain one exact `jk` job identity and discard tracking parameters. Ambiguous IDs, login/account routes, unsupported origins and insecure URLs are rejected.

The separate **Inspect application controls (read-only)** button works on a dedicated job page on either portal. It exports generic action categories, input types and challenge flags only, with no entered field values or private query tokens. Neither an Apply category nor a Submit category proves that an application is ready or approved.

## Local import and review

Use the actual downloaded path, from the repository folder:

```bash
.venv/bin/python src/chrome_job_import.py --file "/absolute/path/to/indeed-jobs-TIMESTAMP.json" --report data/indeed_chrome_review.json
```

Use `data/naukri_chrome_review.json` for Naukri. The shared importer requires the existing qualification and private profiles to agree; it does not create or overwrite applicant facts. Exports must be within 24 hours, identities must be unambiguous, and any bundled inspection must match that exact job. Existing application history excludes recent duplicates. It never launches a browser or writes an application as submitted.

Optional `--control-workbook PATH` or `--use-control-sheet` retains reviewed Sheet controls, pause and restrictive match thresholds. A paused source returns `control_agent_paused`. Applicant values and job descriptions are kept out of stdout; details remain in the local report. Reports are review-only with `application_ready=false`, `submission_enabled=false`, submitted/confirmed zero.

The earlier Naukri-only importer/review/inspection gates remain available for existing reports. They do not gain Indeed or submission support implicitly.

## Full-description batch on either portal

For an Indeed batch, choose **Set up Indeed batch access**, then **Enable Indeed access** in the setup tab. Chrome may ask for optional site-level access to `*.indeed.com`; it is needed to read the batch's newly opened job tabs, not for current-tab export. A normal extension tab keeps the result available if a native prompt closes the toolbar popup. Return to the Indeed search tab after setup. Declining leaves current-tab export available. Naukri's existing batch access is unchanged.

The setup tab checks without prompting when opened. It identifies missing optional permission in the *loaded* manifest, an unavailable API, invalidated context, user-gesture errors and explicit policy errors; other Chrome errors remain `permission_request_failed`. An ungranted result alone does not prove a policy block or user denial. A sanitized browser error and **Save access diagnostic** are available without reading job, credential, cookie or account data. No permission is enabled automatically; no policy is overridden. If setup fails, open one full job and use the first popup button instead. There is no need to repeat portal login.

On a search page with verified job links, choose **Export full descriptions (up to 20)** and keep the popup open. The worker opens inactive job tabs, checks the exact job ID and matching title/company headers, reads only complete JDs, then closes its own tabs. Naukri JSON-LD fallback must explicitly identify the current posting URL; another posting is never borrowed. It downloads `indeed-jobs-details-<timestamp>.json` or `naukri-jobs-details-<timestamp>.json`, compatible with the shared importer. Redirects, missing/changed headers, unreadable JDs and timeouts have per-job reason codes and empty descriptions; they remain unqualified.

There is a 20-posting cap, bounded per-page probes and a two-minute batch budget; a probe already in progress is allowed to finish within its own bound. Remaining postings are marked `batch_budget_exhausted`. A Naukri homepage without real posting links is not a batch source. Open one full posting or use a real job search page; URLs are never invented from titles.

## Naukri external employer inspection

This existing flow is read-only and user-guided:

1. On the exact qualified Naukri job, choose **Prepare Naukri external Apply review**. This records the job origin/path in session-local storage for 15 minutes.
2. Manually review the source control. A Naukri Apply can submit immediately; this inspection does not authorize clicking it. Proceed only when the control clearly navigates to an employer site and the intended action is authorized.
3. On the employer hiring page, choose **Inspect employer ATS form (read-only)**. Temporary `activeTab` permission applies to that explicit click; no arbitrary-site host permission is requested.
4. The downloaded `naukri-ats-form-inspection-<timestamp>.json` includes the user-selected Naukri reference, destination origin, generic field types, field/question labels and action/challenge categories. The handoff is single-use, expires after 15 minutes and remains **user reported**, not verified browser navigation provenance.
5. The existing `src/naukri_ats_gate.py` checks the source against a qualified Naukri report. It does not authorize filling/submission. Labels are untrusted page text; review the JSON before sharing.

## Permissions and acceptance limits

Required permissions remain `activeTab`, `scripting`, `downloads`, session-local `storage`, and Naukri-only host access for the existing batch. The optional host grant is `https://*.indeed.com/*`, enabled only from the setup page's explicit button for full-description batches. Chrome grants site-level access; this worker uses it only for the exact requested job tabs. Current-tab export does not require it. No cookies, debugger, native messaging or broad tabs permission was added. There is no external upload or background account monitoring.

Popup/batch/API smoke tests use simulated Chrome APIs. DOM fixtures run extraction against synthetic Chromium pages. Three additional runtime tests install the actual extension in isolated Chromium, check native manifest/permission APIs and setup-tab wiring, and reproduce an old-manifest/new-source mismatch. They do not grant access or exercise a real user's Chrome permission prompt. CI installs full Chromium for those tests; the local Work runtime cannot launch it because its process-singleton socket is blocked. The supplied search exports establish partial real capture only. Corrected Naukri extraction, full-JD batches, live Mac permission handling, field writing, resume/Review and submission confirmation remain unverified. Full automatic application support through ordinary Chrome is not implemented yet.

Keep exports local and outside Git. Real submissions still require exact-job approval. Merge/deployment remains gated on release acceptance. See [the latest checkpoint](../../docs/LIVE_CAPTURE_CHECKPOINT.md).
