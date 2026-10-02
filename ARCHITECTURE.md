# Architecture

## Goal
A zero-cost job application agent that discovers jobs, authenticates to supported portals using the user's own sessions, searches by target role, scores relevance, fills truthful applications, prevents duplicates, and submits only after release gates allow it.

## Layers
1. Discovery: Greenhouse/Lever public feeds plus authenticated portal search.
2. Matching: deterministic role, skill, seniority, location and sponsorship scoring.
3. Portal adapters: one adapter per portal so portal changes are isolated.
4. Session/auth: credentials never enter the repository. Browser sessions are stored only in local encrypted storage or a future private runner.
5. OTP: mailbox integration may read only recent login-purpose OTP messages matching the portal. OTP values must never be logged.
6. Application inspector: classifies supported form, unknown required field, CAPTCHA, login/MFA requirement, and duplicate status.
7. Fill/submit guard: truthful known answers only. CAPTCHA, manual MFA, or unknown required answers stop automation.
8. Audit: every decision records portal, job, match result, application state and reason without secrets.

## Release modes
- QA: discovery/search/inspection/fill with test data; live submission disabled.
- Controlled live: daily cap, duplicate guard, real profile, supported portals only.
- Production: only after portal-specific QA and security gates pass.

## Non-goals
- CAPTCHA bypass.
- Fabricated answers.
- Committing credentials, cookies, CVs, OTPs or private profile data.
- Paid AI/API dependency.
