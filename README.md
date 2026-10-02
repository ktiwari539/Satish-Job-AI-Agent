# Satish Job AI Agent

Zero-cost, dry-run-first job discovery, matching and authenticated-portal automation.

## Current phase: LinkedIn/Naukri Search Extraction QA

Implemented:
- Greenhouse and Lever read-only discovery.
- Deterministic role/skill/seniority/location/sponsorship matching.
- Duplicate guard and explainable audit.
- Portal registry for LinkedIn, Naukri, Indeed, Wellfound, Glassdoor, Instahyre, Cutshort, Foundit and Hirist.
- Optional local Playwright persistent-session runtime with no credentials in code.
- LinkedIn and Naukri login probes and role/location search navigation.
- LinkedIn and Naukri selector-based search-result extraction.
- Browser results normalize into the same Job model used by Greenhouse/Lever.
- Tracking parameters are removed and fallback stable job IDs are generated when a portal ID is unavailable.
- Generic form inspection for CAPTCHA, manual authentication and unknown required fields.
- Safe application guard and OTP eligibility rules.
- Architecture, QA, risk, release and zero-cost governance documents.

Still required before LinkedIn/Naukri are marked ready:
- Validate selectors and login state against the user's real account/session.
- Enrich extracted cards with full job descriptions before final scoring.
- Portal-specific application form mapping and resume upload.
- Mailbox OTP connector implementation.
- Fill-only QA using real profile data outside the public repository.
- Controlled live-submit approval.

## Safety
- No paid AI/API dependency.
- No credentials, cookies, OTPs, CVs or personal contact data committed.
- No CAPTCHA bypass.
- No fabricated job-application answers.
- Ambiguous login/extraction state fails closed.
- Live submission remains disabled in QA.

## Branch policy
- `main`: controlled baseline.
- `test/job-ai-agent-zero-cost`: development and QA.
