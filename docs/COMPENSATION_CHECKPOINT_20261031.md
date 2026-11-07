# Numeric compensation checkpoint — 31 October 2026 (Asia/Kolkata)

Branch `fix/resume-radio-screening-20261026`, draft PR #2. The PR records the latest published SHA, final CI URL/counts and this restart checkpoint. No submission, merge or deployment.

## Actual supplied evidence

The terminal attachment at base `4e0b0cc` contains `backend_configuration_required` immediately after `import-answers`. It does not contain `reviewed_answers_imported`; the intended private import therefore failed. Its exact cause is not in that generic error, so do not claim a missing download or a bad profile was proved.

The subsequent full preparation considered ten jobs, enriched nine and exercised seven qualified forms. Convin, proppy.ai and Ownly each still had three unknown required questions with `screening_groups_visible_but_not_extracted`. Axis Max Life and Weekday stopped with `safe_next_control_not_found` after two steps. GobbleCube reported `REVIEW_NOT_REACHED` after one step and Syndigo `NEXT_ACTION_FAILED` before a confirmed transition. One listing was unavailable; two jobs were below threshold. Verified Review, submitted and confirmed counts are zero.

The applicant separately observed alphabetic LPA salary answers in amount inputs. The terminal attachment contains no salary field markup or entered values. The new salary browser cases reproduce that class of failure safely; they are not recordings of the precise live forms.

## Root causes and completed fixes

- Salary formatting previously required certain explicit-unit wording. Bare current/expected CTC and ordinary text inputs could retain `LPA` prose. Two older tests explicitly expected those raw strings; those assertions have been corrected to numeric annual amounts.
- Recognized current/present/last-drawn and expected/desired/expectation salary wording now shares an annual compensation mapping. Following the applicant's requested convention, unscaled annual CTC/salary amounts use rupees. Explicit LPA/lakh fields use numeric lakh amounts. Other currencies, monthly pay, fixed/component-only amounts, ranges and a prompt mixing current and expected salary do not borrow an INR fact.
- All known salary amount inputs, including `type=text`, receive plain digits or a decimal. Valid Indian/western grouping and explicit rupee/LPA notation are parsed exactly using Decimal; commas and unit words are removed from the entered representation. Bare numbers already expressed in the question's unit retain that unit. An explicit source INR amount overrides an LPA target while converting; it is not treated as a lakh amount twice.
- Profile aliases and canonical rupee facts are reconciled before using an automatic profile answer, so a conflicting old alias cannot win just because the question wording changed. Exact applicant answers and approved Sheet decisions retain their existing precedence. Current and expected compensation remain distinct. Observed dropdown labels remain unchanged for selection.
- Native/ARIA validity and stable readback still gate navigation. An employer max/min/step or a rejected number does not authorize changing the amount, inventing a range endpoint, guessing a new currency/scale, removing constraints or choosing a different factual answer.
- Import failures now report `answer_import_failed` with a category such as `reviewed_answers_file_missing`, `reviewed_answers_file_invalid_json` or `private_profile_missing`, without echoing private paths, JSON contents or answers. Schema/row/write failures also remain explicit and atomic.
- The full backend launcher has an optional `--reviewed-answers` argument. While holding the same worker lock, it imports first, prints `reviewed_answers_imported` and only then launches the non-submitting browser flow. Failure returns before browser/DB startup. This replaces the previous sequence where a failed standalone import could be followed by a browser run anyway.
- The screening bridge also reads semantic `aria-labelledby` option text and respects an explicit one-question fieldset/radiogroup when option names differ. It requires exactly one selected semantic option; multiple checked Yes/No options cannot count as confirmation. These are representative additional cases, not a claim that the remaining live radio layout has been captured or fixed.

## Verification and limits

813 unit tests passed locally. Four new real-Chromium compensation tests passed: profile and approved controls through Review with numeric-only validation; visible LPA units over machine amount keys; employer max rejection without factual changes/Next; and grouped rupee amounts from an exact saved answer. Nine native-radio recovery cases passed, including two additional ARIA/generated-name and conflicting-selection regressions. The new salary artifact is `data/compensation_fixture_acceptance.json`, uploaded by both CI browser jobs.

All 88 synthetic browser cases passed locally on Playwright 1.55.0. Four installed-extension tests are excluded from this local run because this runtime denies full Chromium's process-singleton socket; CI runs all 92 cases. The final matrix result is in PR #2. Unit tests, Chromium simulations and isolated native extension checks do not establish an authenticated Mac LinkedIn Review. The Work runtime has no access to the existing Mac browser; do not request login, setup, resume or workbook uploads again.

## Exact next action

Use the existing private reviewed-answer JSON supplied in the prior checkpoint, downloaded to Downloads. This is the same file; no answers need retyping. From the existing Mac project:

```bash
git pull --ff-only origin fix/resume-radio-screening-20261026
bash scripts/verify_linkedin_backend.sh --control-workbook "$HOME/Downloads/Job_Agent_Controls_20261029.xlsx" --reviewed-answers "$HOME/Downloads/Job_Agent_Reviewed_Answers_20261031.json"
```

This launcher stops with a precise reason if the import cannot complete. Fix that reported file/profile condition before attempting the browser run. After one successful import, omit `--reviewed-answers` on later normal runs and use the private editor for newer facts, rather than deliberately replaying an old answer file over subsequent corrections.

Read `application_evidence` in `data/certification/backend-linkedin.json` for actual unknown counts, reason codes, completed steps and verified identity/resume/Submit control at Review. Existing `.blocker.json` reports are privacy-safe structure/count captures; if an affected live form remains blocked, its report is the minimum next evidence, not another search probe. No genuine Review is yet proved by the supplied attachment.

Release still requires ten distinct real unapplied forms and one new Review with the intended selected resume, applicant identity and Submit control verified, plus the historical six-job classifications. Preserve applied-job exclusion `4482859467`, queue progression and per-job explicit submission approval. Do not merge or enable daily submissions until release acceptance.
