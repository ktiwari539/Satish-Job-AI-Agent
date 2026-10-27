# Satish Job AI Agent

Zero-cost, dry-run-first job discovery, matching and authenticated-portal automation.

## Current phase: Real Browser Session QA

Start with [the authentication/JD checkpoint](docs/AUTH_AND_JD_CHECKPOINT.md) for the latest Mac evidence, credential/Apps Script/email-code connection and next command. [Multi-portal history](docs/MULTI_PORTAL_CHECKPOINT.md) and [portal support limits](PORTAL_MATRIX.md) remain available. Live release acceptance remains pending.

The core pipeline is portal-independent:

search -> normalize -> open full JD -> enrich -> eligibility -> match -> cross-portal dedupe -> qualified queue -> application inspection -> fill-only plan.

### Search scope

1. India roles.
2. Global remote roles explicitly allowing worldwide/work-from-anywhere hiring.
3. Overseas roles with explicit visa sponsorship or relocation support.

### Portal foundation

LinkedIn, Naukri, Indeed, Foundit, Instahyre, Cutshort, Wellfound, Hirist, Glassdoor, Greenhouse, Lever and Workday company career sites.

### Implemented

- Public ATS discovery and authenticated-browser foundations.
- Full-JD enrichment.
- India/global/relocation/sponsorship matching.
- Cross-portal duplicate detection.
- Application form inspection and fill-only planning.
- Resume validation/upload support.
- CAPTCHA/manual-auth/unknown-required-field hard stops.
- Local persistent Playwright session runner.
- Portal-by-portal login/session QA status.
- Search probes for authenticated portals.
- Automatic live submission disabled by default; a controlled one-attempt pilot requires explicit approval and an allowed IST application window.
- Manual applications can be recorded locally to prevent re-application.

### Real-session QA

See `REAL_SESSION_QA.md`.

The default QA/debug workflows do not submit. The standalone live pilot requires explicit `--approve-one-live-application`, the configured time window, and qualification gates. Credentials and browser session files stay outside Git.

### Still required before controlled live applications

- Run real-session QA locally using the user's own portal accounts.
- Add portal-specific login/search/form selectors where generic probes fail closed.
- Run fill-only QA against real qualified application forms.
- Add mailbox OTP integration where permitted.
- Explicitly approve and enable a small controlled live-submit batch.

No credentials, cookies, OTPs, CVs or personal contact data are committed to this public repository.

## Safe recovery after an unconfirmed Submit click

A `pilot_unconfirmed` / `confirmation_not_detected` result **after**
`submission_click_completed` is NOT permission to retry. LinkedIn may
have accepted the application despite the missing confirmation UI.

Check the **exact** LinkedIn job in the same saved browser profile, without
opening Easy Apply or clicking Submit:

```bash
python src/job_agent_cli.py --portal linkedin --job-url 'https://www.linkedin.com/jobs/view/4461542106/' --check-applied-status-only
```

`linkedin_exact_job_applied_visible` is positive on-page evidence;
`application_status_unverified` means the DOM did not provide evidence,
**not** that the application failed. If unverified, check LinkedIn
**Jobs > My Jobs > Applied** manually for the exact posting before
authorizing another attempt. This read-only status probe never writes the
agent's applications database or reports `confirmed: 1`.

To verify applicant location separately from **search** location:

```bash
python src/job_agent_cli.py --check-profile-city-only
```

Only if the private applicant city is incorrect, set it locally:

```bash
python src/job_agent_cli.py --set-profile-city Mumbai
```

The city command modifies only `data/private_profile.json` on your machine;
it preserves other fields and creates no application attempt. The
`--location` flag is a **job-search filter** and does not update
application answers. An earlier submitted application cannot be
retroactively corrected by changing the local profile.

Diagnostic traces are written to `data/agent_runs/`. They are local
and intentionally omit form values, resume contents and credentials.
They do not automatically stream into this chat or GitHub. After an
approved click, `submission_click_completed` distinguishes a real
Submit click from a merely visible button. `submission_confirmation_checked`
reports whether positive UI evidence was observed.

## Testing vs production application windows

During QA, the test-branch CLI supports `--testing-mode` to ignore the
**production clock schedule only**. It still requires an explicitly approved
**single exact LinkedIn job**, a qualifying JD (75%+ and 3+ evidence skills),
eligibility, 90-day duplicate checks, a configured resume, and at most
**one live attempt per invocation**. If submission is uncertain or fails,
do not retry without renewed approval. The daily confirmed-success cap
remains in force.

Testing at any time (this command **can send one real application**):

```bash
python src/job_agent_cli.py --portal linkedin --job-url 'https://www.linkedin.com/jobs/view/4461542106/' --public-job-url 'https://in.linkedin.com/jobs/view/sr-customer-success-manager-at-firework-4461542106' --testing-mode --approve-one-live-application
```

Production: omit `--testing-mode` and `--allow-outside-window`.
The configured production windows (10:00–12:00 and 23:00–01:00 IST)
continue to apply. The non-submitting `--debug-easy-apply-only` mode
is already unrestricted by time and now inspects Review but never Submit.

## Autonomous non-submitting Easy Apply debugging

Use `--smart-debug` when a selected job has a confirmed Applied indicator or
an ambiguous, unscoped Application status. The agent automatically skips that
job and searches for **one different** title-matching Easy Apply candidate,
checking the local submission ledger and on-page Applied status first:

```bash
python src/job_agent_cli.py --portal linkedin \
  --debug-easy-apply-only --smart-debug \
  --job-url 'https://www.linkedin.com/jobs/view/4481663953/' \
  --query 'Customer Success Manager' --location India --max-jobs 10
```

For a multi-job diagnostic queue, explicitly add `--smart-debug-queue`.
It can continue after a blocked application to inspect the next eligible
candidate, with **at most three actual application-form inspections by default**
(maximum five via `--smart-max-forms`). It automatically skips the supplied
original job and safely skips LinkedIn Applied or ambiguous candidates.

```bash
python src/job_agent_cli.py --portal linkedin \
  --job-url 'https://www.linkedin.com/jobs/view/4481663953/' \
  --query 'Customer Success Manager' --location India --max-jobs 10 \
  --debug-easy-apply-only --smart-debug --smart-debug-queue \
  --smart-max-forms 3
```

The queue prints a safe per-job status followed by `smart_queue_complete`.
**Without** `--debug-interactive`, this is unattended QA: each browser closes
after inspecting the job, and unknown required fields remain blocked. This is
intentional, not a successful application or an unexpected cancellation.

**With** `--debug-interactive` in an interactive Mac terminal, the agent
keeps a blocked application open, displays the unknown required question and
its available options in that terminal, and asks the applicant to supply a
truthful answer **once**. The answer is written atomically with 0600
permissions to the gitignored `data/private_profile.json`, never to GitHub
or the structured run log. The agent then retries the same page using that
approved answer and reuses it for future applications. If a real Review page
is reached, it stays open until Enter is pressed; final Submit is not clicked.

```bash
python src/job_agent_cli.py --portal linkedin \
  --query 'Customer Success Manager' --location India --max-jobs 10 \
  --debug-easy-apply-only --smart-debug --smart-debug-queue \
  --smart-max-forms 3 --debug-interactive
```

Review-page navigation is not a completed submission or a passing release
gate. The summary now includes `resume_evidence_state`,
`review_mismatch_count`, `submit_resolver_ready` and
`release_checks_passed` independently. The multi-job queue aggregates
`release_checks_passed` rather than claiming all Review screens are
production-ready. Full acceptance additionally requires real authenticated
LinkedIn browser evidence, correct resume selection and separate submission
authorization.

The LinkedIn screening bridge now reads **whole employer radio questions**
(including styled ARIA controls), groups duplicate hidden/native and styled
options, selects only an answer supported by the applicant's private profile,
uses a real Playwright browser click and verifies the chosen value after React
rerenders. A previously selected portal answer is **not** trusted unless it
matches the profile. Unknown questions still require truthful applicant input
through `--debug-interactive`. The per-job summary shows
`unresolved_required_count` and the queue shows `question_blocked_jobs`,
without persisting private question or answer text in run logs.

Applicant facts already present in the profile are answered without prompting
when a verified alias or supported experience threshold can be resolved.
Unverified employer-specific claims are **not guessed**. This is
fact-based resolution plus optional answer learning, not a general LLM able
to answer every possible question. The debug queue **never** submits an
application. A real submission requires the separate guarded approval path.

This mode does **not** submit any application. It can fill a draft and navigate
Next/Review for **at most one alternate listing** without the queue flag. It will not retry or force
a job with uncertain Applied status, bypass the ledger, or choose answers
not supported by the local private profile. An additional
`--debug-interactive` flag keeps the browser open at eligible screening
blockers so the applicant can correct their own answers. Without
`--smart-debug`, providing `--job-url` always targets that one exact job.
A read-only `--check-applied-status-only` command never falls back to job
search and closes after the single status check.

This is a bounded safe-decision workflow, **not a generative AI reasoning
model**. The agent still cannot interpret arbitrary employer questions
without reliable form extraction and verified applicant facts. Ambiguous
statuses are skipped, not treated as proof of non-application.

## Optional local AI question understanding (non-submitting QA)

The ordinary answer resolver is deterministic and continues to work offline.
For unfamiliar employer wording, `--local-model` can optionally use a
**locally running Ollama model** to identify which *already verified* private
profile fact is being requested. No paid AI API key or remote service is
required. Install Ollama locally and obtain a model such as
`ollama pull qwen2.5:7b` before enabling this option. Model availability
and suitability depend on the user's Mac. This is not enabled by default.

```bash
python src/job_agent_cli.py --portal linkedin \
  --query 'Customer Success Manager' --location India \
  --debug-easy-apply-only --smart-debug --smart-debug-queue \
  --smart-max-forms 3 --debug-interactive --local-model 'qwen2.5:7b'
```

Safety contract: the model connects only to
`http://127.0.0.1:11434/api/generate` and receives employer question text
plus the **names** of available applicant facts, not the private fact values,
resume, browser cookies or credentials. It chooses one existing fact *key*.
Python independently validates the question's scope against that fact and
uses the original saved value to match one portal option. Subjective,
eligibility, demographic, relocation and unverified yes/no claims are not
answered through this route. A missing local server simply leaves the
question unresolved; it does not invent an answer.

`--local-model` is currently **restricted to non-submitting debug mode**.
It does not authorize final Submit or make the PR production-ready. A real
authenticated LinkedIn browser check is still needed to verify the
question/option extraction and review/resume attachment. Unknown applicant
facts should be supplied truthfully in the interactive local terminal once.

Important: `REVIEW_NOT_REACHED` means a Review click did not produce a
verified final Submit control. The agent no longer mislabels that situation
as a contact-details mismatch. Blocker snapshots are captured before the
interactive terminal releases a page.

## Exact LinkedIn job pilot

A LinkedIn search-results link with `currentJobId` identifies **one** job;
the agent canonicalizes it to `https://www.linkedin.com/jobs/view/<id>/`.
No search result, similar role, or alternate listing is used as a fallback.

Inspect the exact job first (no application, resume access, or private-profile read):

```bash
python src/job_agent_cli.py --portal linkedin \\
  --job-url "https://www.linkedin.com/jobs/view/4476701830/" \\
  --inspect-job-only
```

When the authenticated job-detail page exposes Easy Apply but omits the
title/company/JD, use an independently verified **public LinkedIn posting
with the SAME numeric job ID** as an optional read-only JD source:

```bash
python src/job_agent_cli.py --portal linkedin \
  --job-url 'https://www.linkedin.com/jobs/view/4461542106/' \
  --public-job-url 'https://in.linkedin.com/jobs/view/sr-customer-success-manager-at-firework-4461542106' \
  --inspect-job-only
```

This fallback makes a credential-free HTTP request, validates the exact ID,
and applies the normal match, three-skill, eligibility and duplicate checks.
It fails closed if LinkedIn blocks the public fetch or the JD is incomplete.
For a **separately approved** live attempt, supply the same
`--public-job-url` flag, still targeting the canonical exact job ID.
Do not treat a public JD or debug Review screen as permission to submit.

Only after reviewing `exact_job_qualified_for_pilot`, the title, company,
location, eligibility, duplicate status and JD skill evidence, explicitly
approve a **single real** attempt during the configured application window:

```bash
python src/job_agent_cli.py --portal linkedin \\
  --job-url "https://www.linkedin.com/jobs/view/4476701830/" \\
  --approve-one-live-application
```

Both workflows fail closed on a changed job ID, missing job metadata,
insufficient description, or unqualified/mismatched job. The read-only
inspection does not confirm that LinkedIn has an available or working Apply
form. A completed application counts **only** with a positive submission
confirmation. Existing authentication and security challenges still require
human intervention.
