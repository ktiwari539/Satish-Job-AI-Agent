# Satish Job AI Agent

Zero-cost, dry-run-first job discovery, matching and authenticated-portal automation.

## Current phase: Application Inspection + Fill-Only QA

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
- Generic application form field inspection.
- Safe profile-to-field mapping for identity/contact, location, LinkedIn, notice period, experience, current role/company and compensation fields.
- Resume validation and browser upload support.
- CAPTCHA/manual-auth/unknown-required-field hard stops.
- Fill-only browser execution.
- Live submission remains disabled.

### Still required before controlled live applications

- Validate actual field selectors and workflows against the user's real sessions.
- Keep the real profile and CV outside the public repository.
- Add portal-specific handling where generic browser mapping is insufficient.
- Add mailbox OTP integration where permitted.
- Run end-to-end fill-only QA on real qualified jobs.
- Explicitly approve and enable a small controlled live-submit batch.

No credentials, cookies, OTPs, CVs or personal contact data are committed to this public repository.
