# Resume document cards — 1 November 2026 (Asia/Kolkata)

Working branch `fix/resume-radio-screening-20261026`, draft PR #2. Published SHA and final CI are recorded on the PR. No application submitted, merge or deployment.

## Latest actual result

Uploaded run `20261031T192129Z-ca7a390f` used `fa3247d`. Four forms were exercised: Convin, proppy.ai, Axis Max Life and Syndigo. Every form stopped after one step with `resume_document_controls_unmapped`, zero unknown applicant fields, `root_found=true`, `heading_seen=true`, `radio_count=11`, `document_radio_count=0`, `file_input_count=0`. Resume preparation did not run. Zero Reviews, release-ready jobs and submissions.

The previous generic question classification is corrected, but the resume operation is still blocked. This is not successful live preparation. The diagnostics rule out a missing Resume heading in this run and expose failure to map the document controls. No input node exists at the inspection point; this does not establish that the portal has no upload action.

Ownly, GobbleCube and Weekday did not reach forms because current JD selectors and the public fallback returned no description. So Fetch Shop was unavailable. Two other jobs were below the profile threshold. These are separate from resume mapping. The old applied-job exclusion `4482859467` remains skipped with zero attempts.

## Reproduced defect and repair

The filename reader parsed individual text nodes. A filename rendered as adjacent basename/extension spans was visible to the generic field reader but absent from the document mapper. A compound fieldset legend could also be rejected even though its nested Resume title was recognized. The upload path additionally assumed an existing file input, which misses a lazily created or detached native file chooser.

A controlled comparison of `fa3247d` and the repair on the same synthetic eleven-card page reproduces the actual diagnostic: heading present, eleven radios, zero document mappings, zero file inputs and `BLOCKED_RESUME_UNVERIFIED`. The repair maps eleven documents, selects the configured CV and reaches simulated `SUBMIT_READY` with zero unknown fields and zero submissions. The exact live HTML is not in the uploaded log; this proves a matching code failure, not a live replay.

Completed:

- Read visible filename nodes from children upward. Reconstruct a bounded inline filename only when descendants have not already supplied a filename, avoiding a second fabricated name from parent heading/metadata. Multiple filenames remain ambiguous; exact vault/original aliases and manifest provenance remain required.
- Accept nested Resume titles in compound document-group legends, while keeping a real employer question (including one mentioning Resume) in normal truthful-answer resolution.
- Recognize a unique scoped Upload resume/CV button even with no initial file input. Register the file-chooser event before one trusted click, then set the already verified configured local file once. Bound chooser and acceptance waits. A bare Upload cannot substitute for a competing cover-letter/other-document purpose. A click without a chooser blocks; no speculative second click.
- Treat an ambiguous document card as an attachment blocker before Review. Do not choose among multiple filenames or treat a filename suffix as an exact configured document.
- Preserve independent final Review attachment verification, actual selected-state readback, unknown-question gates, duplicate exclusion and explicit job-specific Submit approval.
- Add only `upload_button_count` and `ambiguous_document_count` to the allowlisted inline diagnostics. No filename, field key, applicant value, CV contents or arbitrary error text is emitted.

## Verification and continuation

819 unit tests and all 22 targeted Chromium resume cases passed locally. The five new cases cover eleven fragmented-name cards/compound legends; a detached/lazy chooser with no initial file input; missing chooser and cover-letter isolation; suffix/multiple-document rejection; and a recruiter legend mentioning Resume. Full synthetic and Python 3.9/3.12 plus Playwright 1.55.0/1.64.1 matrix results are recorded on PR #2. Four installed-extension tests require CI because this Work runtime denies full Chromium's process-singleton socket.

No extra ZIP, answer import, workbook/CV upload or login setup is needed for this repair. Live acceptance remains incomplete. On the existing authenticated Mac, pull the published branch and run the existing non-submitting application verification once:

```bash
git pull --ff-only origin fix/resume-radio-screening-20261026
bash scripts/verify_linkedin_backend.sh --control-workbook "$HOME/Downloads/Job_Agent_Controls_20261029.xlsx"
```

Inspect recognized document count, upload-button/ambiguous-document counts, actual resume preparation action, final Review identity/resume/Submit checks and release-ready count. Do not repeat unchanged code as a diagnostic. JD failures and later employer-question/transition failures remain separate outstanding gates. Do not certify the agent from simulations or enable a real submission without that job's explicit approval.
