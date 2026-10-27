# Authentication and JD recovery — 27 October 2026

Branch: `fix/resume-radio-screening-20261026`; PR #2 stays draft/unmerged. Its description records the published SHA and final CI links.

## Actual Mac result

At `492b472`, Playwright 1.60 on Python 3.9 launched Chromium and discovered seven LinkedIn listings. All seven lacked readable JDs; Naukri/Indeed needed sessions. Zero forms/submissions. Startup is no longer the current blocker. This is not live application acceptance.

## Implemented

- The runner now invokes configured credential login rather than immediately skipping unauthenticated portals. It uses existing local per-portal credentials or the Apps Script provider. The exact-job CLI also uses a configured bridge, retaining policy and exact-job submission approval.
- Supported native POST forms on LinkedIn/Naukri/Indeed include email-then-password login. Credentials require an allowed HTTPS portal origin and verified form action; passwords are submitted at most once per portal/run. Unverified JS/SSO/signup forms stop with structural evidence.
- Supported email-code forms use the bridge or one hidden terminal prompt. Noninteractive runs return `EMAIL_OTP_REQUIRED`. CAPTCHA/authenticator/security-key/SMS challenges remain human checkpoints. Codes and passwords never enter reports.
- JD reading skips short placeholders, reads authenticated/public-layout sections, waits through at most 21 hydration probes, and accepts matching-ID JSON-LD. Missing LinkedIn DOM can use the existing cookie-free same-ID public reader, reconciling employer/title. Body/footer text never becomes a JD. Public reading never bypasses an observed authentication/security challenge or authorizes submission.
- Every candidate gets `jd_evidence`: structural counts, lengths, source and classified failure. JD failures also save blocker files. `--no-login`, `--otp-mode auto|manual|none`, and `--no-public-jd-fallback` control behavior.
- The fix branch uses PR CI once per update instead of duplicating OS/browser installs on push.

## Existing Apps Script connection needed

No Apps Script source, deployment URL or API contract was present on this branch or found in default-branch code search; Personal Context was unavailable. The bridge is prepared source, **not deployed or connected to real Gmail**. An existing project's URL/API contract or sanitized handler source is needed to wire it correctly. Do not overwrite an existing `doPost`. New deployment remains subject to release approval.

Prepared files: `apps-script/JobAgentAuthBridge.gs`, `apps-script/appsscript.json`, `src/auth_bridge.py`. Signed POST operations are `credentials` and `email_otp`. HMAC, bounded timestamps, persistent request nonces and a script lock protect requests. GET releases nothing. The client follows only Google's ContentService response redirect and sends no key in a URL.

Configure these privately in **Script Properties**, never source:

| Property | Purpose |
| --- | --- |
| `BRIDGE_SHARED_KEY` | Random shared key, at least 32 characters |
| `EMAIL_LINKEDIN`, `PASSWORD_LINKEDIN` | LinkedIn account |
| `EMAIL_NAUKRI`, `PASSWORD_NAUKRI` | Naukri account |
| `EMAIL_INDEED`, `PASSWORD_INDEED` | Indeed account |
| `SHARED_EMAIL`, `SHARED_PASSWORD`, `SHARED_PORTALS` | Optional fallback; comma-separated expressly allowed portals |
| `OTP_SENDERS_LINKEDIN`, `OTP_SENDERS_NAUKRI`, `OTP_SENDERS_INDEED` | Exact sender addresses from verified portal login emails |

The manifest enables Advanced Gmail with `gmail.readonly`. A bounded search checks the current account, configured sender, Google DMARC-pass alignment, recipient, login/security-code subject, Google receipt timestamp after this login and within five minutes, one unambiguous code, and no prior use of that message. Reset/signup/application mail, stale/future messages and ambiguous matches are rejected. HTML-only/unrecognized templates use manual fallback. Only the code/timestamp is returned; no mailbox content is exported. One-use markers store message-ID hashes/timestamps, not codes.

After the existing deployment contract is checked (or deployment is approved), configure the Mac connection once:

```bash
.venv/bin/python src/auth_bridge_setup.py
```

The URL and hidden shared-key prompt create gitignored `data/auth_bridge.json` with mode 0600. Secrets stay local. Without the bridge, existing `data/portal_credentials.json` entries work; an `external_default` is shared only with portals expressly listed in its root `shared_portals` array. Never guess/reuse another account's password.

## Verification and continuation

Local validation: 628 unit tests, 28 Chromium fixture tests and 20 Node/Apps Script checks, plus compile/shell/extension checks and offline qualification smoke. CI covers Python 3.9/3.12 and Playwright 1.55.0/1.64.1. These are synthetic tests; no deployed script, actual mailbox or authenticated Mac account was exercised here.

New measured fixture: logged-out Naukri -> configured sign-in -> two discovered jobs -> one missing-JD skip -> next suitable form reaches verified Review -> zero Submit clicks. Evidence: `docs/evidence/auth-jd-fixtures-20261027.json`.

Exact next Mac step after pulling:

```bash
bash scripts/certify_portals.sh --portals linkedin,naukri,indeed --max-jobs 10
```

No repeated runtime setup is needed after the successful Playwright 1.60 launch. Share `data/certification/portals.json` and referenced structural blocker files only. Also provide the existing Apps Script URL/API contract, without secrets, for connection review.

Remaining: actual verification of the seven LinkedIn JDs, real credential/OTP/layout acceptance, Issue #3's six historical classifications and ten distinct real unapplied forms with one verified Review. Never retry manually applied job 4482859467. No real submission without approval for that job; no merge/deployment before release acceptance.

API references: [Web apps](https://developers.google.com/apps-script/guides/web), [Properties](https://developers.google.com/apps-script/guides/properties), [Advanced Gmail](https://developers.google.com/apps-script/advanced/gmail), [message receipt timestamps/headers](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages), [ContentService redirects](https://developers.google.com/apps-script/guides/content).
