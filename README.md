# Satish Job AI Agent

Zero-cost, dry-run-first job discovery, matching and authenticated-portal automation.

## Current phase: Portal Foundation + Match Quality V2

Implemented:
- Greenhouse and Lever read-only discovery.
- Deterministic role/skill/seniority/location/sponsorship matching.
- Duplicate guard and explainable audit.
- Portal registry for LinkedIn, Naukri, Indeed, Wellfound, Glassdoor, Instahyre, Cutshort, Foundit and Hirist.
- Authenticated-browser adapter contract.
- Safe application guard: unknown required answers, CAPTCHA and manual-auth challenges stop automation.
- OTP eligibility rule: only recent login-context messages matching the portal may be consumed.
- Zero-cost, architecture, QA, risk and release-gate documentation.

Not yet implemented:
- Real browser login adapters for individual portals.
- Mailbox connector implementation.
- Portal-specific form filling.
- Live submission.

## Safety
- No paid AI/API dependency.
- No credentials, cookies, OTPs, CVs or personal contact data committed.
- No CAPTCHA bypass.
- No fabricated job-application answers.
- Live submission remains disabled in QA.

## Branch policy
- `main`: controlled baseline.
- `test/job-ai-agent-zero-cost`: development and QA.
