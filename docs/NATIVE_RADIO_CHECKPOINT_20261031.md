# Native radio recovery — 31 October 2026 (Asia/Kolkata)

Working branch `fix/resume-radio-screening-20261026`, draft PR #2. Published commit and CI are recorded in that PR. No submission, merge or deployment.

## Actual Mac evidence

The two supplied terminal captures from base `7e38188` show ten processed jobs, seven qualified application forms, zero verified Review and zero submissions. The private reviewer received thirteen explicit answers: nine Yes/No answers were rejected against an extracted option list containing only `on`; four numeric/text answers were saved. On the second run three jobs still had three unknown questions each and four other forms stopped at `NO_SAFE_NEXT_ACTION`. This is not successful live acceptance.

Native radios without a value attribute expose the browser default `on`. That value does not identify Yes or No. The old field scanner exported it when associated labels were missing, and the reviewer rejected the applicant's real choices. Separately, choosing the first `.jobs-easy-apply-form-section` could scope the screening bridge to a contact/header section and miss later questions. The captures do not contain the exact live DOM, so the new DOM variants are representative regressions, not a claim that the precise live markup was captured.

## Completed changes

- Shared semantic option extraction for screening, field capture and checked-state readback. It reads associated/ARIA labels or a unique visible leaf beside one radio. It excludes `on`, numeric machine values and combined Yes/No text. Hidden native controls can use an unambiguous visible option wrapper; actual checked state must follow the browser click. It never writes checked state or maps `on` to Yes.
- Inline progress scopes the entire active wizard before individual sections. Named groups can find a bounded common ancestor without borrowing another question's prompt from a shared React wrapper. Independent groups are kept separate.
- Private pending captures omit native defaults, and the reviewer tolerates old `options: ["on"]` files without discarding a typed truthful answer. Saving an answer still does not prove selection or acceptance.
- `python3 src/agent_backend.py import-answers --file /private/path.json` validates a complete reviewed batch before one atomic mode-600 write. It preserves unrelated profile data, supports idempotent reimport and explicit edits, retains exact job scope and refuses an active worker. Editing a shared fact supersedes older spellings and imported snapshots of that same fact, so a stale private answer cannot mask the correction. It does not change Sheet controls, approvals or submission settings. Actual applicant answers are returned privately outside this repository.
- A local private check imported all thirteen supplied answers. Nine Yes/No and three exact numeric answers build fill plans. The supplied client-count range remains a range; an exact numeric input still needs the applicant's exact current count. Explicit `NA - 0` is represented as `0` for numeric inputs; bare NA never becomes zero. The actual notice-period wording is recognized as a verified shared fact.
- Required-radio validation checks one selected option per named group, while required checkboxes remain explicit. The fallback validator scopes the active wizard instead of unrelated background inputs. `PreparationEvidence` now includes completed steps and allowlisted navigation/selection reason codes. This helps distinguish a disabled Next from a missing or wrongly scoped control.
- The preparation revision includes both shared radio modules so blocked jobs are reconsidered after this update/import. Existing duplicate checks, manual exclusion `4482859467`, truthful-answer gates and per-job submission approvals remain active.

## Verification

799 unit tests passed locally. Seven new Chromium synthetic regressions passed on Playwright 1.55.0: native `on` with visible siblings, hidden native controls, multiple inline sections, missing semantics, a shared React wrapper, required group/checkbox validation, and private import through Review. Zero Submit clicks. The new synthetic artifact is `data/native_radio_fixture_acceptance.json`; CI uploads it for each browser version. Final full-suite results and CI are recorded in PR #2.

The Work runtime's full Chromium persistent-context tests cannot start because its local socket is denied (`process_singleton_posix.cc`, `Operation not permitted`). The normal headless DOM/browser simulations run. The four installed-extension tests must be assessed in CI, independently of the Mac session. No local restriction is bypassed.

The four live `NO_SAFE_NEXT_ACTION` outcomes are not all diagnosed from the supplied counts. The required-group bug is established in code and covered by a real-browser regression; it is not proof that it caused all four live stops. New reason codes will show which control state remains blocked. No new live form or resume verification was performed from Work.

## Exact continuation

Download the private reviewed-answer JSON supplied with this checkpoint into Downloads. From the existing Mac project:

```bash
git pull --ff-only origin fix/resume-radio-screening-20261026
.venv/bin/python src/agent_backend.py import-answers --file "$HOME/Downloads/Job_Agent_Reviewed_Answers_20261031.json"
bash scripts/verify_linkedin_backend.sh --control-workbook "$HOME/Downloads/Job_Agent_Controls_20261029.xlsx"
```

This uses the existing authenticated browser, workbook, profile and resume; do not repeat search-only probes, setup, login or data uploads. The queue revises blocked attempts and proceeds across jobs. Assess `application_evidence` for `flow_state`, `flow_reason_codes`, `steps_completed`, unknown counts and actual verified identity/resume/Submit control at Review. The range answer must not be replaced with a midpoint or a number inferred from the JD. If an exact current count is requested, edit that actual prompt through the existing private reviewer.

Release remains blocked on authenticated Mac evidence: ten distinct unapplied forms exercised and at least one new Review with verified identity, the intended selected resume and Submit control. Preserve the distinction between unit tests, Chromium simulations, installed-extension API tests and actual LinkedIn. Never submit without explicit approval for that particular job.
