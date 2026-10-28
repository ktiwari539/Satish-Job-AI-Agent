# Ordinary Chrome integration — 28 October 2026

Branch `fix/resume-radio-screening-20261026`; PR #2 remains draft/unmerged. Its description records the exact latest SHA and CI. No deployment or real application was performed.

## Live evidence and scope

The applicant now reports successful login to **both Naukri and Indeed in ordinary Chrome**. Do not repeat the terminal-browser login attempts or ask for passwords/cookies. This is user-reported account access, not a successful Playwright login or certified extension run. LinkedIn's agent-browser session was separately confirmed on the Mac at 07:46 IST on 28 October.

Google rejected the automation-browser OAuth route; its rejection handling remains in place. Regular Chrome sessions are used locally through deliberately invoked extension scripts. They are not transferred into Playwright or exposed to Python. The Apps Script project/Sheets manifest exists, but private bridge configuration and live Sheet reads remain unverified. Apps Script is separate from this browser integration.

## Implemented

- Extension **0.5.0**, named **Satish Job Agent - Chrome Bridge**, retains the existing `browser-extension/naukri` directory so it can be installed/reloaded in place. It supports current-tab Naukri and Indeed job exports. Indeed uses only explicit `activeTab` access; no extra host, cookies, debugger or broad tabs permission was added.
- Indeed dedicated job pages use the existing `#jobDescriptionText` family of supported DOM selectors. Unknown layouts/missing JDs fail closed. Search cards never borrow a potentially stale selected-panel JD. No generic account/body fallback is used.
- Indeed `jk`/`vjk` identity is retained as a single canonical `/viewjob?jk=...` URL. Tracking/fragments are removed. Duplicate/conflicting keys, invalid IDs, non-job/account routes, credentials in URLs, non-HTTPS and foreign hosts are rejected. Naukri legacy export behavior is preserved.
- A current-job export bundles read-only application-control inspection. The popup refuses to download when the job ID changes between capture and inspection. No Apply or Submit control is clicked; entered values, credentials, cookies and account data are not captured.
- `chrome_job_import.py` accepts both portals, validates an export within 24 hours (bounded future clock skew), correlates any inspection to the exact job and reuses full-JD qualification and existing application dedupe. It requires the existing private profile and checks profile consistency. Search snippets/short JDs remain unqualified. Only a structural summary is printed; job details stay in the local report.
- Optional `--control-workbook` / `--use-control-sheet` use the same reviewed controls, pause and restrictive threshold rules. An import never resumes a paused control. Reports always remain `submission_enabled=false`, `application_ready=false`, submitted/confirmed zero. Only approved application flows may later produce submission evidence.

## Verification

670 unit tests include 12 new import/identity/privacy/consistency/pause cases. Five new real-Chromium **synthetic DOM** cases exercise dedicated Indeed capture -> Python review, distinct search IDs, conflicting/account/foreign routes, missing-JD isolation and existing Naukri capture. The full browser suite now has 40 cases. A new Node smoke suite simulates Chrome popup/API wiring and tests exact-job race handling and unchanged permissions. Existing extension/ATS and 34 bridge checks remain in place. See PR #2 for actual passed checks and CI.

These checks do not prove that the packaged extension works on the applicant's current live portal layouts or that Chrome permission handling is accepted on their Mac. No actual job capture, Chrome field filling, selected resume, Review or submission was exercised here. The regular-Chrome route currently captures job/control data only; a verified field writer and approved submission adapter are still outstanding.

## Exact next step on the Mac

1. Pull the working branch once:

```bash
git pull --ff-only origin fix/resume-radio-screening-20261026
```

2. In the already signed-in **ordinary Chrome**, open `chrome://extensions`, enable Developer mode and **Load unpacked** → `Satish-Job-AI-Agent/browser-extension/naukri`. If already installed, use Reload. Verify the name above and version **0.5.0**. Keep the existing logins.
3. Open one actual full job-description page on each portal. On Indeed, open the individual job in its own tab (`/viewjob?jk=...`), rather than only selecting a search sidebar. On Naukri use the `job-listings-...` page. Do not click Apply for this capture.
4. Click the extension → **Export current job / search** on each job tab. This produces `naukri-jobs-<timestamp>.json` and `indeed-jobs-<timestamp>.json` in Downloads, with the corresponding application-control evidence bundled. Review the two files before sharing; they are the minimal missing live evidence. Do not send a whole browser profile, credentials or cookies.
5. Local scoring, when desired, uses the actual downloaded path (one file per command), for example:

```bash
.venv/bin/python src/chrome_job_import.py --file /absolute/path/to/indeed-jobs-<timestamp>.json --report data/indeed_chrome_review.json
```

Use `data/naukri_chrome_review.json` for the Naukri report. Existing verified `config/qa_profile.json` and `data/private_profile.json` must agree; missing/conflicting facts stop import. Supply the reviewed control source when using Sheet controls; a paused source returns `control_agent_paused`. Import success means review-only job qualification, never application readiness.

Next implementation depends on the actual exported layouts/controls. Naukri Apply may submit in one click. A control category alone never grants permission to navigate/fill/submit. All real submissions still need exact-job approval. Keep merge/deployment gated on release acceptance, and never retry manually applied LinkedIn job `4482859467`. Issue #3's real ten-form and verified resume/Review gates remain open.

Prior evidence: [login rejection handling](LOGIN_BLOCKER_CHECKPOINT.md), [Sheet/form checkpoint](SHEET_CONTROL_CHECKPOINT.md), [extension instructions](../browser-extension/naukri/README.md).
