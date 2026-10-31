# Login rejection checkpoint — 28 October 2026

Branch `fix/resume-radio-screening-20261026`; PR #2 remains draft/unmerged. Its description records the exact published SHA and CI results. No deployment or real application was performed.

**Newer evidence:** the user subsequently confirmed login to both portals in ordinary Chrome. Do not repeat the ordinary-Chrome or terminal-browser login checks. Follow [CHROME_BRIDGE_CHECKPOINT.md](CHROME_BRIDGE_CHECKPOINT.md) for extension 0.5.0 and the next two live job exports. The unverified ordinary-Chrome status below describes the earlier investigation stage.

## Actual user evidence

- LinkedIn: `SESSION_CONFIRMED` at `2026-10-28T02:16:06.749837+00:00` (07:46 IST), using the agent's persistent `browser-profile`. This proves login only, not form/resume/Review or submission readiness. Preserve this profile; do not delete it to troubleshoot another portal.
- Naukri/Indeed login attempts in the terminal-launched browser reached Google's “This browser or app may not be secure” rejection. The user also reports unsuccessful direct email/password and mobile OTP attempts in that browser; their specific error messages have not been supplied. Do not label those credential failures or claim they have the same cause.
- A login attempt in ordinary, manually opened Chrome has not yet been verified. No passwords, codes or cookies are needed in chat.
- Apps Script project creation and the read-only Sheets manifest were shown in the user's screenshots. Full bridge source/private properties and any live Sheet request remain unverified. No web-app deployment was shown. A shared key signs Mac-to-Script requests; it does not change Google browser eligibility.

## Implemented correction

`login_blockers.py` recognizes the exact Google rejection on the trusted HTTPS `accounts.google.com` origin. It reads at most five current/related login pages, handles same-tab and popup navigation, and returns a reason code only. Unrelated existing tabs do not invalidate LinkedIn's saved session. No navigation, credentials, cookies, URL parameters or account text are exported.

Interactive `browser_qa.py` checks before navigation and again after the human login checkpoint. New openerless login popups are included. A rejection is saved as `HUMAN_ACTION_REQUIRED / google_browser_security_rejection`, with the URL omitted. It preserves the visible error instead of reloading the portal and masking the evidence. The noninteractive session adapter also stops before credential/OTP lookup on an observed rejection.

This fixes classification and retry guidance. It does not make Google accept the automation browser or provide a certified SSO adapter. Do not add stealth flags, transfer Google cookies, or attach to the default personal Chrome profile. Apps Script credentials do not solve this rejection.

Browser CI now allows 15 minutes for setup plus fixtures, with the fixture step bounded to five minutes. The prior older-browser job spent 7m27s downloading Ubuntu packages, leaving almost no margin under the old ten-minute job limit. Test assertions and browser-version coverage are unchanged.

## Validation

658 unit tests, including nine new rejection/privacy/session-preservation cases. Two additional real-Chromium **synthetic** cases cover a visible Google rejection and an interactive Google popup without reloading the source portal; the full browser suite has 35 cases. Existing 34 bridge checks and both Naukri extension smoke suites remain in place. See PR #2 for actual passed checks and final CI results; no synthetic test proves a real Google or portal login.

## Exact continuation

1. Stop repeating Google/password/OTP attempts in the terminal-launched browser. Open ordinary Google Chrome directly, visit the existing Naukri and Indeed accounts, and attempt their normal supported login once each. Record only success/failure and any exact nonsecret error text. Do not reset passwords or create new accounts as a diagnostic.
2. If ordinary Chrome works, the existing [Naukri extension](../browser-extension/naukri/README.md) can capture job descriptions and inspect supported application controls there. That path is read-only: it does not yet automate applications or certify submissions. Indeed does not have an equivalent verified extension integration on this branch. Keep its automated application path blocked until an allowed login/integration is verified.
3. If ordinary Chrome also fails, use the exact portal/Google error to distinguish an account, portal or browser-wide restriction. Do not infer a bad password from the automation-browser message.
4. Continue LinkedIn acceptance independently once verified applicant facts and pause/control gates allow it: ten distinct unapplied forms, classified failures and at least one verified resume/Review. The previously manually applied job `4482859467` must never be retried. Do not repeat LinkedIn login diagnostics after the confirmed session unless a new run loses it.

Per-job approval still governs real submissions; release acceptance still governs merge/deployment. Prior code, form and Sheet evidence is in [SHEET_CONTROL_CHECKPOINT.md](SHEET_CONTROL_CHECKPOINT.md); private setup is in [APPS_SCRIPT_SETUP.md](APPS_SCRIPT_SETUP.md).

Official guidance: [Google supported browsers and automation restrictions](https://support.google.com/accounts/answer/7675428?hl=en), [Playwright persistent profiles and default-profile limitations](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context).
