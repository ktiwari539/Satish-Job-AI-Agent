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
- Live submission disabled.
- Manual applications can be recorded locally to prevent re-application.

### Real-session QA

See `REAL_SESSION_QA.md`.

The local runner never submits applications. Credentials and browser session files stay outside Git.

### Still required before controlled live applications

- Run real-session QA locally using the user's own portal accounts.
- Add portal-specific login/search/form selectors where generic probes fail closed.
- Run fill-only QA against real qualified application forms.
- Add mailbox OTP integration where permitted.
- Explicitly approve and enable a small controlled live-submit batch.

No credentials, cookies, OTPs, CVs or personal contact data are committed to this public repository.

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
