# First Apps Script project

The applicant confirmed on 27 October 2026 that no Apps Script project exists. There is no existing endpoint or handler to obtain. The bridge source is prepared and tested in this repository; no Google project or deployment has been created by this work.

## Recommended arrangement

| Component | Responsibility |
| --- | --- |
| Python agent on the applicant's Mac | Saved browser sessions, portal login, job matching, duplicate checks, form filling, resume checks, Review and approved submissions |
| Existing Google Sheet | Config and reviewed Question_Bank answers; no passwords or OTPs |
| New private standalone Apps Script project | Signed, bounded read-only Sheet requests and expressly configured per-portal credentials |
| OTP initially | Hidden local terminal prompt, using `--otp-mode manual` |
| Optional later permission | Read-only Gmail lookup for a fresh supported login challenge, with exact verified sender addresses |

Apps Script does not run the Playwright browser or create missing applicant facts. An unknown required question remains a blocker for that job, and the queue continues. Authentication can still require a human checkpoint for CAPTCHA, SSO, SMS or unsupported layouts. Each actual application submission continues to need approval for that exact job.

Use a **standalone project**, owned only by the applicant, rather than placing credentials in a script bound to a potentially shared Sheet. Script Properties are project configuration, not an independently access-controlled password vault: project editors can read them. Keep project edit access private. Existing saved sessions or local credentials remain available if a cloud bridge is not wanted.

## Prepare the project without deploying

1. Sign in to the Google account that owns the control Sheet. Open [Apps Script](https://script.google.com/) → **New project**. Name it `Satish Job Agent Bridge`. Do not add collaborators.
2. Replace the starter `Code.gs` contents with [JobAgentAuthBridge.gs](../apps-script/JobAgentAuthBridge.gs).
3. In **Project Settings**, enable **Show "appsscript.json" manifest file in editor**. Paste [appsscript.json](../apps-script/appsscript.json) into that manifest. This initial profile enables Advanced Sheets and `spreadsheets.readonly`, with no Gmail permission. If the project uses a standard Google Cloud project, enable the corresponding Sheets API there as well.
4. Under **Project Settings → Script Properties**, add the properties below. Enter values directly in Google's project settings; do not put them in the Sheet, source, GitHub or chat.

| Property | Initial value |
| --- | --- |
| `CONTROL_SHEET_ID` | The existing spreadsheet's ID, between `/d/` and `/edit` in its URL |
| `BRIDGE_SHARED_KEY` | A freshly generated random secret, at least 32 characters; retain it privately for the Mac setup |
| `EMAIL_LINKEDIN`, `PASSWORD_LINKEDIN` | Actual LinkedIn credentials, if automatic sign-in is wanted |
| `EMAIL_NAUKRI`, `PASSWORD_NAUKRI` | Actual Naukri credentials, if automatic sign-in is wanted |
| `EMAIL_INDEED`, `PASSWORD_INDEED` | Actual Indeed credentials, if automatic sign-in is wanted |

Generate the shared key with a password manager's random generator. Configure credentials only for accounts that exist. Leave optional shared-password and OTP-sender properties unset initially. A common email address does not imply that different sites have the same password.

5. Save the project. Keep the Sheet paused in `VALIDATION` while reviewing setup. **Do not deploy yet**: merge/deployment remains gated on release acceptance under the user's instructions. Creating source and private properties does not start the agent or submit applications. The project URL may be shared for identification; it does not by itself give this workspace edit access or provide the Mac's deployment endpoint. Do not share screenshots of private properties.

## Connection after deployment is approved

The current Python transport uses HMAC-signed HTTPS POSTs, not Google browser cookies or Google OAuth. A reviewed web-app deployment must execute as the owner and allow those signed requests to reach `doPost`. Choosing an access setting requiring Google sign-in will not work with this transport. If account/domain rules disallow the required endpoint access, retain the local provider/XLSX workflow instead of weakening those rules. The shared key must be private; the URL alone never authorizes a bridge request. GET requests release nothing.

After release acceptance and approval of that deployment configuration, create a versioned web-app deployment using **Deploy → New deployment → Web app**. Use the production `/exec` URL, not an editor or `/dev` URL. Configure the Mac once:

```bash
.venv/bin/python src/auth_bridge_setup.py
```

This prompts for the URL and a hidden shared key, then writes gitignored `data/auth_bridge.json` with mode 0600. It does not request portal credentials or read the mailbox. Then verify the connection with a bounded read:

```bash
.venv/bin/python src/sheet_control.py --use-control-sheet
```

It should report control counts and paused validation state without printing applicant values. For subsequent explicitly authorized preparation QA, use `--use-control-sheet --otp-mode manual` with the existing portal certification command. A paused Sheet stops preparation; this guide does not turn it on or grant submission approval. Reconcile missing or conflicting applicant facts before changing controls.

## Add automatic email OTP later, if wanted

After credential/session verification, explicitly review the broader mailbox permission before replacing the project's manifest with [appsscript.email-otp.json](../apps-script/appsscript.email-otp.json). This adds Advanced Gmail and `gmail.readonly`; the scope permits mailbox reading, although this bridge's code searches only configured login messages. It cannot be narrowed to a single sender through the OAuth scope. A standard Cloud project also needs the Gmail API enabled. Review Google's new authorization request and update the deployed version only after approval.

Set `OTP_SENDERS_LINKEDIN`, `OTP_SENDERS_NAUKRI` or `OTP_SENDERS_INDEED` only from verified login-message sender addresses in that same Google account. Do not guess sender addresses or configure password-reset messages. `--otp-mode auto` can then fetch one fresh supported email code reached during the current login; manual entry remains the fallback. Existing challenges, ambiguous codes, unsupported templates, SMS and CAPTCHA still require the applicant.

## Acceptance and continuation

Local simulations and CI do not prove a live Google deployment or portal login. Outstanding evidence is: one signed live Sheet read, actual supported credential/session/OTP verification, real form/resume/Review checks and Issue #3's ten distinct unapplied forms. Keep PR #2 draft; do not merge, deploy or submit without the applicable acceptance/approval. Never retry manually applied job `4482859467`.

**Exact next step:** create the private standalone project and copy the prepared source/default manifest. There is no old backend to locate. The user's Google account is required for project creation and private property entry; no repeated browser-runtime diagnostics are needed.

References: [standalone projects](https://developers.google.com/apps-script/guides/standalone), [manifest editor](https://developers.google.com/apps-script/concepts/manifests), [Script Properties](https://developers.google.com/apps-script/guides/properties), [advanced services](https://developers.google.com/apps-script/guides/services/advanced), [web apps and execution identity](https://developers.google.com/apps-script/guides/web).
