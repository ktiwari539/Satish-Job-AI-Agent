# LinkedIn form checkpoint — 31 October 2026

Branch `fix/resume-radio-screening-20261026`, draft PR #2. PR head/CI records the exact published SHA. No real submission, merge, deployment or schedule installation.

## Actual result and remaining gap

The applicant ran the search inspector at `2fb877b`: **seven verified search jobs**, zero identity conflicts, zero missing employer/location fields, one probe, no loading/login/challenge signals. This is actual Mac search evidence. The inspector deliberately never opens forms, so its `application_form_exercised: false` does not measure a form-completion rate. [Safe supplied counts](evidence/linkedin-live-search-20261031.json).

Live end-to-end preparation remains unproven. Do not report synthetic pass rates as a real success rate. Do not ask for another search inspection, login/setup, CV, workbook export or the prior Naukri/Indeed captures. The existing control workbook loaded correctly in the earlier backend run. This Work environment cannot operate the Mac's authenticated browser.

## Implemented correction

Search canonicalized slugged links, but the exact-job handoff compared URL strings; the inline form, recovery and final-review route guards also required numeric-only paths. The same posting could be rejected under a slug, the alternate LinkedIn hostname or a consistent `currentJobId` parameter. Reproduction tests failed on the previous code. This is an independently established bug, not a claim about a form failure on the applicant's latest search-only run.

Exact page, inline entry/recovery, final-review route and applied-status checks now use the same posting-ID contract. Trusted numeric/slugged view variants resolve to one ID. A selected search URL may identify an input job but never proves an exact detail surface. Conflicting/blank/duplicate selected IDs, wrong jobs, HTTP, foreign hosts and nonstandard ports are rejected. Applied-control scoping retains the exact ID on a slugged page. Approval, truthful-answer, eligibility, resume and Review gates remain required.

## Measured tests

- **765 local unit tests passed**, including the failing-before/passing-after URL cases and rejection cases.
- Real Chromium with routed synthetic HTML exercises complete search-card metadata through full JD, qualification, inline contact/resume/screening and Review after the SPA changes the URL to a same-ID slug. Two forms exercised: first blocked on an unknown certificate answer, next prepared with identity, selected resume and Submit control verified. Zero Submit clicks. [Synthetic form evidence](evidence/linkedin-complete-flow-fixtures-20261031.json).
- A separate Chromium case proves a scoped Applied control on a slugged page blocks entry with zero application clicks. The nine prior discovery cases also pass locally. These eleven cases are synthetic, separate from live LinkedIn.
- Compile, shell syntax and whitespace checks pass. The full Python 3.9/3.12 and Playwright 1.55.0/1.64.1 matrix must pass in PR #2. Isolated native extension tests remain a separate scope; extension stays 0.6.3.

## Exact next action on the Mac

Run the actual preparation workflow using the existing working workbook:

```bash
git pull --ff-only origin fix/resume-radio-screening-20261026
bash scripts/verify_linkedin_backend.sh --control-workbook "$HOME/Downloads/Job_Agent_Controls_20261029.xlsx"
```

This existing launcher searches up to ten jobs, opens full JDs, checks eligibility/deduplication, fills known answers, verifies the resume and advances supported eligible forms to Review. It does not log in or submit. A blocked job advances to the next candidate. The search inspector is no longer the next action.

Share the terminal JSON or the categorical report at `data/certification/backend-linkedin.json`; no credentials, cookies, applicant answers or CV contents are needed. The next Work session must inspect the first failing **JD / eligibility / application-entry / field / resume / Review** stage in that report and fix the demonstrated cause. If a job reaches Review, first verify its actual selected resume and release checks, then continue toward ten distinct real unapplied forms. Preserve manual exclusion `4482859467` and the original historical six-job classifications. Submission still requires explicit per-job approval. Do not declare the project complete before those live gates pass.
