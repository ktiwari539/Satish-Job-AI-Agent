# Satish Job AI Agent

Zero-cost, dry-run-first job discovery, matching and authenticated-portal automation.

## Search scope

The agent is not India-only. It supports three parallel search tracks:

1. India roles.
2. Global remote roles that explicitly allow worldwide/work-from-anywhere hiring.
3. Overseas roles with an explicit visa-sponsorship or relocation-support signal.

Unverified overseas roles are not auto-qualified because the candidate requires sponsorship outside India.

## Portal scope

Current foundation includes:
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

Additional ATS/portal adapters can be added without changing the core matcher.

## Current phase

Implemented:
- Greenhouse and Lever read-only discovery.
- LinkedIn/Naukri browser search navigation and result normalization.
- Deterministic role/skill/seniority/location/sponsorship matching.
- International sponsorship, relocation and worldwide-remote signal detection.
- Duplicate guard and explainable audit.
- Safe application guard and OTP eligibility rules.

Still required:
- Real-account validation for authenticated portals.
- Full JD enrichment before final scoring.
- Portal-specific application form mapping and resume upload.
- Fill-only QA using real profile data outside the public repository.
- Controlled live-submit approval.

## Safety

- No paid AI/API dependency.
- No credentials, cookies, OTPs, CVs or personal contact data committed.
- No CAPTCHA bypass.
- No fabricated job-application answers.
- Live submission remains disabled in QA.
