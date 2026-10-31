# Sheet controls and verified answers — 27 October 2026

**Superseded live state:** on 29 October the applicant authorized REVIEW preparation and worldwide discovery; the previously unresolved row and mode dropdown were reconciled through connected-Sheet edits/readback. The existing resume was also recovered from its Sheet-named Drive source. See [latest checkpoint](LIVE_CAPTURE_CHECKPOINT.md); the paused workbook snapshot below is historical, not current controls.

Branch `fix/resume-radio-screening-20261026`; PR #2 remains draft/unmerged. Its description records the exact latest SHA and CI link. No real application or deployment was performed.

## Latest actual evidence

The user's Mac output at `81bdd589` discovered seven LinkedIn jobs, read six full JDs, qualified five and exercised one application form. Concentric AI stopped on five unknown fields; four other qualified jobs had an unclassified entry blocker. One job was unqualified and one JD remained unavailable. Naukri/Indeed reported missing credentials. Zero verified Reviews and zero submissions. The JD recovery is working on six listings; this does not certify the remaining form/attachment gates.

The supplied workbook **snapshot** has Config, Question_Bank, Applications, Run_Log, Exceptions and Dashboard. Config is paused (`agent_enabled=FALSE`) in `VALIDATION` mode. Question_Bank has eight rows: seven reviewed automatic answers and one unresolved India work-authorization row. This snapshot was inspected read-only, without refreshing or editing the original Google Sheet. No applicant values, credentials, workbook or private source ID are committed to the repository.

## Implemented

- `sheet_control.py` reads the existing Config/Question_Bank schema from an XLSX export or a signed, read-only Apps Script operation. It validates headers, sizes, booleans, dates, duplicate rows, units, approval/source metadata and the 90-day answer-review window. Notes and credential cells are not exported by the bridge.
- Automatic answers require an explicit reviewed Approved Answer, Auto Answer=YES and a recognized verified source. Patterns use exact normalized matching, never keyword/regex instructions or universal “Yes.” Existing fact resolvers still handle safely scoped quantities. Unknown answers remain blocked.
- Notice days, overall experience and annual-INR compensation are checked against existing private facts. Explicit LPA/annual-INR equivalents are supported; monthly or ambiguous units are not guessed. Conflicting saved answers/facts report field or row identifiers only.
- Unresolved/disabled answers take precedence over saved answers, derived quantities and ordinary field mappings. India's unresolved authorization remains unknown, even if older configuration says Yes. Per-portal identity/contact information and the trusted resume remain in their existing private sources.
- Sheet overlays remain in memory. Interactive answer learning persists only the applicant's new manual answers over the original local profile, without copying temporary Sheet controls or imported facts into it.
- Config roles, locations, remote preference, excluded companies and title exclusions can restrict qualification. Score/cap settings only tighten existing policy. Pause stops before browser/resume access. Exported snapshots cannot authorize live runs; live controls cannot replace exact-job approval or release gates.
- `certify_portals.py` and `job_agent_cli.py` accept `--control-workbook PATH` or `--use-control-sheet`. These are opt-in. Existing runs without a control source keep their current behavior.
- LinkedIn entry evidence now retains the structured classifier and entry state instead of collapsing every entry failure into `application_entry_requires_portal_adapter`.
- Supported first-party JavaScript login forms with no explicit action/method use a guard that prevents native GET submission before credentials are entered. The page's JavaScript may sign in; positive session verification remains mandatory. Explicit/foreign form actions, security challenges and unrecognized flows remain gated.

## Private connection

Keep portal email/password pairs in Apps Script **Script Properties** (`EMAIL_LINKEDIN`, `PASSWORD_LINKEDIN`, etc.) or the existing private local provider. Optional shared credentials require an express portal allowlist. Config/Question_Bank must not become a password/OTP store.

The prepared bridge adds `control_snapshot` using Advanced Sheets and `spreadsheets.readonly`. Set private `CONTROL_SHEET_ID` in the reviewed Apps Script project. The server reads only `'Config'!A1:C200` and `'Question_Bank'!A1:H1001` from that configured ID; callers cannot select another spreadsheet. The default manifest has no Gmail access; a separate `appsscript.email-otp.json` profile adds optional read-only mailbox access.

The user clarified that **no Apps Script project exists**. Follow [the new-project guide](APPS_SCRIPT_SETUP.md) to prepare a private standalone project, using the default no-mailbox manifest and manual OTP initially. There is no existing service URL/API contract to request. Keep project editors private because Script Properties hold project-wide credentials. No Google project or deployment was created here; deployment still requires release review.

## Verification

Local checks: 649 unit tests; 33 distinct Chromium fixture tests; 20 authentication/mail plus 9 control/Apps Script checks; compile/shell/extension checks and offline qualification smoke. Five additional permission-profile checks verify the default no-mailbox setup and optional Gmail manifest, and prove credential/control operations work without Gmail. CI verifies Python 3.9/3.12 and Playwright 1.55.0/1.64.1. See PR #2 for final results.

New browser evidence: approved sheet answer -> known field -> verified Review with identity/resume/Submit control and zero Submit clicks. A separate unresolved-authorization fixture refuses the old Yes. JS login fixtures prove session verification and prevention of default GET credential URLs. These are synthetic pages and simulated Google APIs, not actual authenticated portals, Sheets or Gmail.

Saved nonprivate evidence: `docs/evidence/control-workbook-validation-20261027.json` and `docs/evidence/control-form-fixtures-20261027.json`.

## Exact continuation

1. Follow [APPS_SCRIPT_SETUP.md](APPS_SCRIPT_SETUP.md): create a new owner-only standalone project and copy the prepared source/default manifest. Enter private properties in the user's Google account. Keep deployment gated on release acceptance; no existing backend or repeated runtime diagnostics are needed.
2. For a local export, inspect without credentials/CV/browser:

```bash
.venv/bin/python src/sheet_control.py --control-workbook /absolute/path/to/Job-Ai-Agent.xlsx
```

3. Once the live bridge connection is reviewed and configured, validation reads use:

```bash
bash scripts/certify_portals.sh --use-control-sheet --otp-mode manual --portals linkedin,naukri,indeed --max-jobs 10
```

A paused control returns `control_agent_paused`; this work does not turn it on. Resolve the authorization row and any other genuinely missing applicant facts before live acceptance. Capture actual screening questions through the existing explicitly interactive debug flow if their facts are absent; never invent them. Verify the four entry classifications, resume/Review behavior and real credential/OTP flows on the user's Mac. Issue #3's historical six classifications and ten distinct real unapplied forms with one verified Review remain open. Never retry manually applied job 4482859467; each real submission requires exact-job approval. Keep PR draft and do not merge/deploy until release acceptance.

API references: [Sheets batchGet](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/batchGet), [Advanced Sheets](https://developers.google.com/apps-script/advanced/sheets). Prior auth/setup context: `docs/AUTH_AND_JD_CHECKPOINT.md`.
