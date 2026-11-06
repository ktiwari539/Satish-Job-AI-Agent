# Resume-control regression checkpoint — 1 November 2026 (Asia/Kolkata)

Branch `fix/resume-radio-screening-20261026`, draft PR #2; no submission, merge or deployment. Published SHA and final CI are recorded on PR #2.

## Evidence consumed

The newly attached terminal output confirms the Mac pulled `7ab88f2` and ran the full backend launcher. Run `20261031T184227Z-418ebfdf` attempted six qualified forms. Every form stopped after one completed step with one unknown field, `screening_groups_visible_but_not_extracted`, an empty `resume_preparation_action`, `resume_evidence_state=not_checked`, and an empty `pending_questions_report`. Zero Reviews, release-ready jobs and submissions. The earlier run on `0b4c6e4` reached four Reviews, all blocked by a resume mismatch. This is a regression, not an improvement justified by passing simulations.

All six current failures are before resume preparation. That consistent pattern narrows investigation to common UI/control recognition rather than six missing applicant answers. An empty pending report does not reveal the prompt: private question capture excludes filenames, generic labels and sensitive text, or may fail to record an unsupported control. The terminal log contains counts and categories, not the exact live DOM or input labels. The precise live layout remains unverified.

Syndigo was not exercised as a form in this run: its job description was unavailable through both the current DOM selectors and the public fallback. So Fetch Shop's listing was unavailable. Two other candidates were below the matching threshold. These failures are separate from the six form failures. Applied exclusion `4482859467` remained skipped with zero attempts.

## Reproduced regression and repair

A controlled comparison ran the old published code and the repair against the same synthetic application page. Its title is `<div>Resume <small>Required</small></div>` with two native saved-document choices. On `7ab88f2`, heading recognition fails and a filename becomes one unknown recruiter question (`BLOCKED_UNKNOWN_REQUIRED_FIELDS`, unknown count 1). The repaired code reaches `SUBMIT_READY` with verified identity, configured selected document, zero unknown fields and zero Submit clicks. That state is simulated readiness only; it does not authorize or prove a real submission. This demonstrates a real code weakness consistent with the log, not a replay of LinkedIn's unavailable live HTML.

- Detect Resume/CV titles from short visible text nodes and accessible heading labels, including nested required indicators and accented Résumé. Ignore editable content, scripts and styles. No arbitrary whole-page substring is used as an applicant answer.
- Prefer a bounded application scope that actually includes the Resume title, rather than a smaller progress/footer subtree. Preserve independent-wizard ambiguity rejection and never choose body/html as the active wizard.
- Recognize bounded deep document cards and visible `aria-labelledby` / `aria-describedby` document-name references. Selected-document evidence uses the same card recognition, and still requires actual checked/selected state, exact configured/vault-original filenames and valid local provenance. An unselected listing is not attachment proof.
- A fieldset/radiogroup with a separate employer question is not reclassified merely because its answer options are filenames. Mixed required recruiter questions retain normal verified-answer resolution.
- If a filename-only radio still cannot be mapped, fail closed as `resume_document_controls_unmapped` without pretending it is a missing applicant fact or navigating forward.
- `resume_control_diagnostics` now appears directly in blocked terminal evidence. It contains only a fixed status, scope/title booleans and bounded radio/document/file-input counts. It never includes field keys, labels, filenames, answers, file contents or arbitrary exception text. This distinguishes a missing scope/title, an unparsed card, a read-only Review and a failed probe without another separately packaged diagnostic file.

## Validation and limits

819 unit tests passed locally. All 17 targeted Chromium resume cases passed, including the previous upload/selection safeguards plus wrapped/accessible titles, deep ARIA-named cards outside the progress footer, employer questions with document options, unmapped-document classification, and two independent ambiguous wizards. A baseline/repaired comparison reproduced one unknown on the old code and zero on repaired simulated Review, with zero submissions in both. Full synthetic regression and Python 3.9/3.12 plus Playwright 1.55.0/1.64.1 CI results are recorded on PR #2. The four installed-extension tests require CI because this Work runtime denies full Chromium's process-singleton socket.

No additional upload is needed to implement this repair. Do not ask for the old ZIP again, re-import the original reviewed answers, redo login/setup or request the CV/workbook. Current live resume verification, the later employer questions and Convin's final transition are still not certified. Passing unit/browser simulations is not authenticated portal evidence.

## Exact continuation

From the existing authenticated Mac project, pull the published branch and run the existing non-submitting full launcher once against this repair:

```bash
git pull --ff-only origin fix/resume-radio-screening-20261026
bash scripts/verify_linkedin_backend.sh --control-workbook "$HOME/Downloads/Job_Agent_Controls_20261029.xlsx"
```

Inspect Review/release-ready counts, `resume_preparation_action`, selected-resume evidence and, on any remaining control block, the new inline `resume_control_diagnostics`. Do not repeat the same run against unchanged code or use a search-only probe as application acceptance. The current six empty pending paths do not justify asking the applicant for six answers; only a genuinely captured employer question may require a new fact. Release remains blocked until Issue #3's real-form and final Review gates pass. Each real submission still requires explicit job-specific approval.
