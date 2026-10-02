# Satish Job AI Agent

Zero-cost, dry-run-first job discovery, matching and authenticated-portal automation.

## Current phase: Multi-Portal + Full-JD QA

The core pipeline is portal-independent:

search -> normalize -> open full JD -> enrich -> eligibility -> match -> cross-portal dedupe -> qualified queue -> application inspection.

### Search scope

1. India roles.
2. Global remote roles explicitly allowing worldwide/work-from-anywhere hiring.
3. Overseas roles with explicit visa sponsorship or relocation support.

### Portal foundation

- LinkedIn
- Naukri
- Indeed
- Foundit
- Instahyre
- Cutshort
- Wellfound
- Hirist
- Glassdoor
- Greenhouse
- Lever
- Workday company career sites

### Implemented

- Greenhouse/Lever public discovery.
- LinkedIn/Naukri browser result normalization.
- Multi-portal search/start-route catalog.
- Full-JD browser enrichment with portal-specific selectors plus fail-closed fallback.
- Role, skill, seniority, experience, India/global-remote, sponsorship and relocation rules.
- Cross-portal duplicate detection so the same company/title/location is not processed twice.
- Audit logging and zero-cost safeguards.
- Live submission disabled.

### Release gates still required

- Validate authenticated portals using the user's own real browser sessions.
- Validate each portal's live selectors.
- Application form field mapping and resume upload.
- Mailbox OTP integration where permitted.
- Fill-only end-to-end QA with the real private profile.
- Controlled live test before production.

No credentials, cookies, OTPs, CVs or personal contact data are committed to this public repository.
