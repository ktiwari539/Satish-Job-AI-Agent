# Answer recovery checkpoint — 31 October 2026

Branch `fix/resume-radio-screening-20261026`, draft PR #2. The PR records the published SHA and final CI. No real submission, merge or deployment.

## Actual evidence

The supplied Mac run at `7af378e` discovered seven jobs, verified seven full JDs through the exact-ID public fallback, qualified four and exercised four application forms. All four stopped at unknown required questions: counts **5, 4, 3, 3**. Three other jobs were below the match threshold. No application reached verified Review; submitted/confirmed remain zero. [Safe summary](evidence/linkedin-question-blockers-20261031.json).

The attachment contains counts, not question wording. Do not claim these exact questions have all been answered. Resume/identity mismatches reported before Review were not evidence of a separate resume/identity failure. The Work runtime cannot operate the authenticated Mac browser. Existing workbook, resume, profile, saved session and prior captures remain in place; do not request them again.

## Implemented

- Deterministic matching of common contact, current employer/title, education, total/role experience, notice-period and salary wording. Explicit INR/LPA and days/year conversions use verified quantities. Current and expected compensation stay distinct. Overall experience never becomes industry, technology or certification experience. Ambiguous currency, monthly pay, ambiguous slash dates and inexact lower bounds remain unresolved.
- The backend now uses the existing strict resume-fact extractor for missing facts, both initially and during current-input revalidation. Applicant/Sheet facts retain precedence. It does not infer role tenure from an overall career summary or replace an explicit user fact.
- Reviewed control answers work across the supported wording/unit variants. Unapproved scopes and conflicting private/control facts remain blocked. Exact employer-specific answers may be stored per job; they cannot silently answer another employer's question. Shared facts are edited in the private profile, preserving unrelated fields.
- Typed values are formatted before filling; dropdown labels stay unchanged even when option values are opaque. Blur commits input validators, and two stable DOM reads verify retention and native/ARIA acceptance. A lost text value gets at most one refill with the same verified answer. Invalid ranges are never clamped, years/salary are never inflated, constraints are never removed and rejected choices are never replaced with a different factual answer.
- Actual unresolved or rejected questions are captured before navigation closes the page in private `data/questions/pending.json` (atomic, mode 600). No entered answers, credentials, cookies, screenshots or HTML are stored there. This file contains prompt/option text and stays outside Git/CI artifacts. Shareable traces retain counts instead of unanswered prompt text.
- `review-questions` lets the applicant answer or explicitly replace a saved answer locally. Normal shared facts update their canonical private fields, including unit conversions; employer-dependent facts are scoped to the exact job. A changed profile revises the durable queue on the next run so NEEDS_INPUT jobs are reconsidered. A Sheet-held decision must be reviewed in the Sheet; a private answer cannot bypass it. The editor refuses an active worker.
- Review checks are reported only after Review is reached. A question-stage stop reports `review_exercised: false`, zero Review mismatches and resume `not_checked`, plus the private pending-question path when prompts could be extracted.

## Tests and limits

**789 local unit tests passed.** Eight new real-Chromium synthetic cases passed: verified wording/unit fields through Review; one-time reactive text recovery; persistent rejection stops without Next; a range never inflates experience; opaque dropdown options retain their label; equivalent numeric formatting without rounding; a reused input key on a different question cannot receive a stale retry; and an actual unknown prompt saved privately, answered explicitly, then reaching verified identity/resume/Review on rerun. Zero Submit clicks. The seven existing multi-portal Chromium cases also passed locally. Compile, shell syntax and whitespace checks pass.

[Synthetic answer-format evidence](evidence/answer-recovery-fixtures-20261031.json) records only fixed counters, no applicant/financial answers. Full Python 3.9/3.12 and Playwright 1.55.0/1.64.1 CI is required in PR #2. Synthetic fixtures and isolated native-extension checks are separate from actual LinkedIn acceptance. Extension stays 0.6.3.

## Exact continuation on the Mac

```bash
git pull --ff-only origin fix/resume-radio-screening-20261026
bash scripts/verify_linkedin_backend.sh --control-workbook "$HOME/Downloads/Job_Agent_Controls_20261029.xlsx"
```

This full preparation run uses the existing verified facts and new format handling. It never logs in or submits. If an actual fact is still missing or rejected, the report points to the private pending questions. Review them locally:

```bash
.venv/bin/python src/agent_backend.py review-questions
```

Type the truthful answer or a correction; Enter skips and `:stop` ends. No existing answer is printed. New employer-dependent answers are scoped to that job; normal profile facts are reusable. Then rerun the same full preparation command to verify the retained field values and resume/Review. The editor itself opens no browser, changes no Sheet and submits nothing. Do not share its private questions or answers in GitHub/chat; the backend's counts and categorical blockers are sufficient for continuation.

If unknown counts remain but the pending path is empty, prompt capture or the local private write was unavailable. Check the active form structure and local file availability; this is not proof that the applicant lacks the information. Inspect the corresponding structural blocker evidence before changing answer rules. If a current-source conflict remains, reconcile the verified source rather than overriding it to pass.

Next Work session: inspect which of the four live forms now reaches Review and the first remaining field/format/layout blocker. Do not repeat search/login/setup. Still require ten distinct real unapplied forms, a genuinely new verified selected-resume Review and historical six-job classifications. Preserve exclusion `4482859467`; explicit per-job approval remains required for submission.
