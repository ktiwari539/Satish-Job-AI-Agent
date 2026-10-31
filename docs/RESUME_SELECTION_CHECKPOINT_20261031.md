# Configured resume selection checkpoint — 31 October 2026 (Asia/Kolkata)

Branch `fix/resume-radio-screening-20261026`; draft PR #2 remains unmerged. The PR records the published head and final CI. No real submission or deployment.

## Actual Mac evidence

The newly uploaded terminal log is run `20261031T165207Z-0c81c2b4` on `0b4c6e4`. Ten candidates were considered, nine enriched and seven qualified. Four jobs reached Review: Ownly (4477505979), Axis Max Life (4474057601), GobbleCube (4482861546) and Weekday (4483021006). Each verified identity and Submit control, but each reported `different_resume_selected`. Zero jobs passed release checks; zero were submitted. A mismatch classification is evidence of contradictory selected-document names, not proof of the remote file's bytes.

Convin (4484922670) completed two steps with zero unknown fields but did not reach final Review. Proppy (4481880094) completed three steps and retained one unverified question. Syndigo (4459650984) progressed to three completed steps but retained four controls not extracted as screening groups. Weekday's prior salary blocker is absent. The new log does not contain those remaining question texts, selected filenames, rendered DOM or entered answers.

The earlier uploaded ZIP contains the previous pending questions, not the current pending file from this run. All original reviewed answers are already imported on the Mac. Do not request that old ZIP, another answer import, the CV/workbook again or new login/setup. The existing vault, authenticated browser and control workbook are retained. Actual live end-to-end acceptance remains incomplete.

## Completed repair

The flow previously inspected the saved resume without reliably choosing the configured document. It now prepares a positively identified bounded Resume step before the normal field planner:

- Validate configured local file and vault manifest/digest before mutation. Choose one exact saved vault/original filename using a trusted click and verify the selected state remains after a render delay.
- If no uniquely selectable matching card exists, use one unambiguous Resume upload input and upload the configured bytes once. An explicitly labelled cover-letter/portfolio/certificate/transcript input is never substituted. If upload adds a new card without selecting it, select that exact card once and verify it.
- Bound selection readbacks, allowing up to roughly five seconds for upload acceptance; do not repeat uploads or choose arbitrarily among duplicate cards/ambiguous upload controls. A rejected or reverted selection blocks before navigation.
- A configured local file input alone is pending evidence. It may progress to Review only when no positively wrong selection remains. Final Review must independently verify the intended document; its mismatch gate is unchanged. Resume preparation does not operate on a final Submit screen.
- Share document-choice recognition across screening, generic fields and required-choice guards. Only proven document controls are excluded. A recruiter question on the same Resume step still requires a verified answer. Ignore stale filename-to-`on` mappings and prevent a second generic upload after preparation.
- Report allowlisted `resume_preparation_action` and categorical failure evidence, without filenames, paths, answers or CV contents. Include the new module in durable preparation revision hashing so affected jobs are reconsidered.

## Verification scope

818 unit tests passed locally. Twelve new Chromium simulations passed, covering saved document selection through its label; one upload plus accepted-card selection; rejected upload; local-file-only progression and independent Review; duplicate saved cards; ambiguous and correctly labelled uploads; mixed recruiter questions; selection reverted by the page; final Review mismatch; cover-letter isolation; tampered provenance; and read-only final Review.

The complete local headless suite passed all 107 synthetic cases (no skips). After the final bounded upload-wait/readback refinement, the 12 new cases and the complete unit suite passed again. The four installed-extension/native Chrome API tests remain delegated to CI because this Work runtime denies full Chromium's process-singleton socket. Python 3.9/3.12 and Playwright 1.55.0/1.64.1 CI results are recorded on PR #2. Browser CI also uploads `resume_selection_fixture_acceptance.json` containing verified synthetic Review outcomes. These are simulations, not authenticated LinkedIn verification.

## Exact continuation

After pulling the published branch on the existing Mac:

```bash
git pull --ff-only origin fix/resume-radio-screening-20261026
bash scripts/verify_linkedin_backend.sh --control-workbook "$HOME/Downloads/Job_Agent_Controls_20261029.xlsx"
```

This is one non-submitting application verification of the new CV preparation, using the existing login, vault and already imported answers. Check `application_evidence` for `resume_preparation_action`, `resume_evidence_state`, Review identity/Submit checks and release-ready count. Do not treat the previous four Reviews as acceptance of this new code.

For the remaining questions, the minimal missing input is the **current existing** Mac `data/questions/pending.json` from the latest run; the older ZIP cannot reveal those current prompts. No need to make another ZIP or retype known facts. A control-mapping failure requires the current rendered control structure rather than an invented answer. Convin's `final_review_not_rendered` also remains unresolved without current rendered transition evidence.

Release still requires ten distinct real unapplied forms exercised and one new Review passing all release gates, plus historical six-job classifications. Preserve applied-job exclusion `4482859467`. Every actual submission requires explicit approval for that specific job; scheduled/debug runs remain non-submitting.
