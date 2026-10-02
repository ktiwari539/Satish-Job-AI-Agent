# Satish Job AI Agent

Zero-cost, dry-run-first job discovery, matching and authenticated-portal automation.

## Current phase: LinkedIn/Naukri Browser Adapter QA

Implemented:
- Greenhouse and Lever read-only discovery.
- Deterministic role/skill/seniority/location/sponsorship matching.
- Duplicate guard and explainable audit.
- Portal registry for LinkedIn, Naukri, Indeed, Wellfound, Glassdoor, Instahyre, Cutshort, Foundit and Hirist.
- Optional local Playwright persistent-session runtime with no credentials in code.
- LinkedIn login probe and role/location search navigation.
- Naukri jobseeker-session probe and role/location search navigation.
- Generic form inspection for CAPTCHA, manual authentication and unknown required fields.
- Safe application guard and OTP eligibility rules.
- Architecture, QA, risk, release and zero-cost governance documents.

Still required before LinkedIn/Naukri are marked ready:
- Validate login against the user's real account/session.
- Extract and normalize search result cards into Job records.
- Portal-specific application form mapping and resume upload.
- Mailbox OTP connector implementation.
- Fill-only QA using real profile data outside the public repository.
- Controlled live-submit approval.

## Safety
- No paid AI/API dependency.
- No credentials, cookies, OTPs, CVs or personal contact data committed.
- No CAPTCHA bypass.
- No fabricated job-application answers.
- Ambiguous login state fails closed.
- Live submission remains disabled in QA.

## Branch policy
- `main`: controlled baseline.
- `test/job-ai-agent-zero-cost`: development and QA.
