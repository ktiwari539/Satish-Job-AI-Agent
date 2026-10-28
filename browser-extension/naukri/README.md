# Naukri from your ordinary Chrome (no automated Google login)

Google can refuse OAuth login inside Playwright-managed Chromium with
"This browser or app may not be secure." Do **not** try to disguise automation,
copy Google/Naukri cookies, or bypass Google's security controls.

This small, **read-only** Chrome extension instead uses the Naukri tab where
you have already signed in yourself using Google's normal account chooser.

## Set up once

1. Use the working branch `fix/resume-radio-screening-20261026` in your local repository.
2. Open normal **Google Chrome** (not the agent's Chromium window).
3. Open `chrome://extensions`; enable **Developer mode**.
4. Choose **Load unpacked** and select the folder
   `Satish-Job-AI-Agent/browser-extension/naukri`.
5. Sign in normally on `https://www.naukri.com/` using Google in Chrome.
   The extension does not observe Google sign-in.

## Capture job search and full JD

1. After updating the branch, visit `chrome://extensions` and click the
   **Reload** icon on this unpacked extension. Version **0.2.0** adds optional
   `naukri.com` site access (for job pages) and the downloads permission.
   Approve only if you want batch enrichment.
2. Open a Naukri job search result page in the signed-in Chrome window.
3. Click the extension. Choose **Export full descriptions (up to 20)**. The
   extension opens up to 20 Naukri job posting pages in inactive tabs,
   extracts job-description text only, then closes its tabs. Keep the
   extension popup open until you see a completion message.
4. It downloads `naukri-jobs-details-<timestamp>.json` even when some postings
   cannot be read. Those jobs remain unqualified rather than being guessed.
5. Import the newest full-description batch JSON:

   ```bash
   latest="$(find "$HOME/Downloads" -maxdepth 1 -type f -name 'naukri-jobs-details-*.json' -print | sort | tail -n 1)"
   if [ -n "$latest" ]; then
     .venv/bin/python src/naukri_browser_import.py --file "$latest"
   else
     echo "No Naukri full-description export found yet."
   fi
   ```

6. Review `data/naukri_import_report.json` to see scores and
   `QUALIFIED_FOR_REVIEW` decisions.

The original **Export search listings** still works and requires only the
current active tab, but search exports have no complete JD and will show
`NEEDS_FULL_JD`. On an individual detail page, the original button also
captures the displayed description.

## Start supervised application review (no submission)

After a batch import reports qualified jobs, select the highest-scoring job
from the local report and open **only that one job** in regular Chrome:

```bash
.venv/bin/python src/naukri_review_queue.py --open-first
```

This consumes `data/naukri_import_report.json`, enforces the original score
threshold and accepted decisions, and does **not** click Apply.

Reload extension version **0.4.1** at `chrome://extensions`, open the
individual job in regular signed-in Chrome, then click
**Inspect application controls (read-only)**.

It downloads a `naukri-application-inspection-<timestamp>.json` containing
only generic button categories, required input types, safe Apply-link **origins**
(without URL paths, query tokens, or user data) and security/challenge flags.
It does **not** record form values, PII, passwords, cookies, or account data.

Each inspection must be correlated to the exact qualified URL in the current
local report before any application work. For a downloaded inspection:

```bash
.venv/bin/python src/naukri_inspection_gate.py \
  --inspection "$HOME/Downloads/naukri-application-inspection-YYYY-MM-DD.json"
```

### Manually inspect an external employer ATS

Version **0.4.1** introduces a user-controlled handoff for Naukri's
`external_apply` control that does **not** reveal a link destination before
clicking:

1. Update the test branch, then reload the unpacked extension in
   `chrome://extensions`; verify version `0.4.0`. Approve its added
   **storage** permission (used only for a 15-minute, session-local source job
   reference). There is no new arbitrary-site host permission.
2. On the **specific qualified** Naukri job page, click the extension's
   **Prepare external Apply review** button. This stores only the Naukri job
   origin/path, with no query string or cookies.
3. Close the extension popup and manually review the wording of the Apply
   button. If it clearly says **Apply on company website**, you may click it
   yourself to open the employer's job application. If it looks like a direct
   Naukri submission, do not click based on these instructions.
4. On the external employer hiring form tab, reopen this extension and click
   **Inspect employer ATS form (read-only)**. The extension uses Chrome's
   temporary **activeTab** permission from that explicit click. No
   external-domain host permissions are requested.
5. The extension downloads `naukri-ats-form-inspection-<timestamp>.json`
   with a source Naukri job reference, destination **origin only**, generic
   input field types, visible field/question labels, and control/challenge
   categories. No entered field values, account tokens, cookie data,
   sensitive selected options, uploaded file names, or URL query strings
   are captured. Inspect the JSON locally before sharing it.
6. The handoff is single-use and expires after 15 minutes. If it expires,
   return to the Naukri job and use **Prepare** again.

**Security:** The ATS inspector refuses Google sign-in, unrelated non-hiring
pages and non-HTTPS pages. Labels may include employer screening questions,
so review them before sharing. It does not fill, navigate through forms,
click Submit, detect confirmed submissions, or record an application as
successful. Capturing a form is not application confirmation.

If a report contains an external-Apply control, inspect the employer ATS
separately. On-site Naukri Apply may be one-click submission: **do not click
automatically on the basis of these pre-application scans**.

The current workflow is intentionally non-submitting. No automated
application submission or success claim exists yet.

### Permissions and limitations

The optional batch needs `tabs`, `downloads`, and **Naukri-only** site
access. It never visits Google sign-in, clicks Apply, reads account profile
details, or transfers cookies or tokens. It does not make independent requests
to any API; it loads selected job pages inside ordinary Chrome. Pages blocked
by Naukri or with missing descriptions remain unqualified. Limit is 20
postings per explicit user click.

The export does not contain Chrome cookies, OAuth tokens, account chooser data,
Google passwords, login OTPs, Naukri profile details or private contact fields.
The extension requires `activeTab`, `scripting`, `downloads` and session-local `storage`, plus Naukri-only host permissions for the optional batch. All collection starts after an explicit click; there is no credential access or external upload.

**Limitations:** This is read-only job discovery and scoring. Browser DOM
selectors can change. Captured search cards are not treated as full JD. Batch enrichment is best-effort and requires live validation.
The importer cannot apply for jobs or confirm submissions. The future
supervised browser-side application adapter is **not implemented yet**.

Files are local. Do not commit exports to GitHub.

## Architecture audit (2026-10)

**GO for read-only discovery and manual form inspection only. NO-GO for
unattended or automatic application submission.**

The user-selected Naukri job reference is not proof of the browser's
external navigation. The current ATS inspection has unverified provenance.
Use `src/naukri_ats_gate.py` to confirm the source URL belongs to a
qualified job before starting further work. This gate does not authorize
submitting an application.

Chrome's temporary `activeTab` permission is suitable for a deliberately
invoked form inspection. It is not a general, persistent ability to interact
with arbitrary employer ATS pages. Full unattended application flows need a
separately approved, scoped portal adapter and robust submission evidence.

The scanner does not intentionally read field values, but labels are
untrusted page text and may contain personal information despite basic
redaction. Inspect the generated JSON before sharing it.

The mock-based CI tests do not prove real-world Chrome permission handling,
ATS compatibility, successful submission, or daily throughput. A completed
application must have confirmation evidence and deduplication recorded.

