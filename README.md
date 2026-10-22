# Satish Job AI Agent

Zero-cost, dry-run-first job discovery, matching and authenticated-portal automation.

## Current phase: Real Browser Session QA

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
