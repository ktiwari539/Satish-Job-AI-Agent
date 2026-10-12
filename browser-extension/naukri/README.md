# Naukri from your ordinary Chrome (no automated Google login)

Google can refuse OAuth login inside Playwright-managed Chromium with
"This browser or app may not be secure." Do **not** try to disguise automation,
copy Google/Naukri cookies, or bypass Google's security controls.

This small, **read-only** Chrome extension instead uses the Naukri tab where
you have already signed in yourself using Google's normal account chooser.

## Set up once

1. Pull the branch `test/job-ai-agent-zero-cost` in your local repository.
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
     /Users/satish.tiwari/.venv/bin/python src/naukri_browser_import.py --file "$latest"
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
/Users/satish.tiwari/.venv/bin/python src/naukri_review_queue.py --open-first
```

This consumes `data/naukri_import_report.json`, enforces the original score
threshold and accepted decisions, and does **not** click Apply.

Reload extension version **0.3.1** at `chrome://extensions`, open the
individual job in regular signed-in Chrome, then click
**Inspect application controls (read-only)**.

It downloads a `naukri-application-inspection-<timestamp>.json` containing
only generic button categories, required input types, safe Apply-link **origins**
(without URL paths, query tokens, or user data) and security/challenge flags.
It does **not** record form values, PII, passwords, cookies, or account data.

Each inspection must be correlated to the exact qualified URL in the current
local report before any application work. For a downloaded inspection:

```bash
/Users/satish.tiwari/.venv/bin/python src/naukri_inspection_gate.py \
  --inspection "$HOME/Downloads/naukri-application-inspection-YYYY-MM-DD.json"
```

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
The extension requires `activeTab`, `scripting`, `tabs`, and `downloads`, plus Naukri-only host permissions for the optional batch. All collection starts after an explicit click; there is no credential access or external upload.

**Limitations:** This is read-only job discovery and scoring. Browser DOM
selectors can change. Captured search cards are not treated as full JD. Batch enrichment is best-effort and requires live validation.
The importer cannot apply for jobs or confirm submissions. The future
supervised browser-side application adapter is **not implemented yet**.

Files are local. Do not commit exports to GitHub.
