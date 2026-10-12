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

1. Open a Naukri job search result page in the signed-in Chrome window.
2. Click the extension and **Export jobs to JSON**. A job-only JSON is downloaded.
3. Import it locally, replacing the filename with your actual downloaded file:

   ```bash
   /Users/satish.tiwari/.venv/bin/python src/naukri_browser_import.py --file "$HOME/Downloads/naukri-jobs-YYYY-MM-DDTHH-MM-SS.json"
   ```

4. Search results can produce a list, but they **cannot be scored without a
   sufficiently complete job description**. Open a relevant individual Naukri
   job detail page, click the extension, export again and import that JSON too.
5. Review `data/naukri_import_report.json` to see scores and
   `QUALIFIED_FOR_REVIEW` decisions.

The export does not contain Chrome cookies, OAuth tokens, account chooser data,
Google passwords, login OTPs, Naukri profile details or private contact fields.
The extension has only `activeTab` and `scripting` permissions and operates
on a tab after an explicit click. It does not make network requests.

**Limitations:** This is read-only job discovery and scoring. Browser DOM
selectors can change. Captured search cards are not treated as full JD.
The importer cannot apply for jobs or confirm submissions. The future
supervised browser-side application adapter is **not implemented yet**.

Files are local. Do not commit exports to GitHub.
