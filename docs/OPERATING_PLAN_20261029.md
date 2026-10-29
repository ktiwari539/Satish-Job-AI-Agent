# Job agent operating plan — 29 October 2026

**Backend milestone delivered:** the persistent preparation queue, local API, pause/resume, bounded lease recovery, current-input submit guard and atomic capacity reservations are now implemented and connected to certification. Resume-derived role tenure is also limited to explicit duration statements. See [backend checkpoint](BACKEND_CHECKPOINT_20261029.md) for 743 local unit tests, ten synthetic forms across a restart, final CI and the new non-submitting Mac acceptance command. This does not enable daily production or satisfy real LinkedIn acceptance.

The requested outcome is daily, profile-matched applications across India, eligible overseas roles and remote roles. The user now wants one setup and standing authorization within reviewed facts, filters and a configurable daily limit. Routine applications should not require repeated permission once a supported production workflow is validated. No daily target or current control value was changed in this work.

This is the operating decision and implementation checkpoint, not a claim that autonomous applications work across all portals. Current code still gates live submission to one approved exact-job pilot. The new scheduled worker only prepares for review and cannot submit. There was no deployment, Mac schedule installation or real application in this continuation.

## Portal selection

These are recommended roles for the channels, not measured rankings of interview yield. Choose by relevant, eligible unique openings and verified outcomes, not the number of portal logos or a promised application count.

| Channel | Intended use | Current evidence / next gate |
| --- | --- | --- |
| LinkedIn | First applicant-facing workflow to streamline; native search/alerts and user-operated application steps, with agent matching and answer preparation outside the site | Existing browser form code is not permission for unattended use. LinkedIn explicitly disallows third-party website automation. Do not schedule that code as an unattended worker. A permitted integration would need separate validation. |
| Naukri | India-focused channel to assess against the reviewed target roles | One actual JD/control export accepted. Automated form/resume/submission and permission for unattended access are unverified. |
| Indeed | Additional India and international job leads | One actual JD/control export accepted. Its jobseeker guidelines prohibit third-party bots applying for jobs; use native or otherwise authorized workflows. |
| Instahyre | Profile-based matching channel; validate relevant inventory for this applicant | Official candidate documentation describes matching using experience and preferences. Registered routes are not a working application adapter. This plan refers to Instahyre, the provider already named in the repository, not the separate InstaHire service. |
| Wellfound | Additional startup/remote opportunities | Official candidate pages describe location and timezone restrictions. A remote label does not establish eligibility to work from India. Adapter and access permission remain unverified. |
| Employer career sites using Greenhouse / Lever | Structured public job discovery, followed by the employer's supported application route | Public feeds already have code support. Target employer board names must be configured. Public reading does not authorize application API writes; Greenhouse submission requires an employer Job Board API key. Real form/resume acceptance remains pending. |
| Other providers, including Workday and country-specific boards | Add only when they supply a material set of eligible jobs and a tested, supported application route | Keep unverified adapters out of unattended execution. |

LinkedIn remains the first user-facing workflow. Public employer-feed review can be validated separately without spending time extending unsupported browser bots. Add Naukri/Instahyre, Indeed and remote channels as their actual integration gates are met; the user is not being asked to repeat old captures or logins.

## Where each part runs

| Component | Location and responsibility |
| --- | --- |
| Browser and review worker | The applicant's Mac initially, using the existing saved agent profile, private profile, resume vault and SQLite ledger. One scheduled worker at a time. The Mac must be awake and signed in. This Work session cannot control that Mac browser. |
| Google Sheet | Reviewable filters, verified screening answers, enable/pause state, operating mode and cap. Refresh controls before a run; unavailable controls stop scheduled preparation. Do not put passwords or OTPs in cells. |
| Apps Script | Short, signed requests for current controls and portal-specific credentials stored in Script Properties. Existing source already implements this for LinkedIn, Naukri and Indeed; the deployed bridge path remains unverified. Project access stays private because Script Properties are shared at script scope. Optional email OTP access is a distinct configuration. |
| GitHub | Versioned source and deterministic tests. Keep applicant secrets, CVs, cookies and production login sessions outside the repository and CI. |
| Always-on hosting | A later option for permitted API workers after local acceptance. No server was provisioned. A browser-dependent workflow cannot be made continuously available by scheduling Apps Script alone; Apps Script currently has a six-minute execution limit. |

The existing Mac launchd times are 10:00 and 23:00 in the Mac's local system timezone. These equal the intended IST starts only when that Mac uses Asia/Kolkata. This change does not install, activate or verify the schedule. Keep schedule availability separate from successful application counts.

## One consistent pipeline

1. Read current controls, reviewed profile facts and exact resume identity. Reuse them; do not repeatedly ask for already supplied facts.
2. Gather supported job leads; retain source, exact posting identity, description, location and hiring-region evidence.
3. Reject duplicates across sources, already applied postings, closed jobs, role/skill mismatches and ineligible locations. Overseas sponsorship and India hiring eligibility must be explicit when needed.
4. Create a prepared application using verified facts. A model may help map question wording and draft text; it must not invent experience, salary, citizenship, authorization or sponsorship answers. Unknown facts become exceptions.
5. Verify the current job, required fields, actual selected resume and final review. A visible Apply button is not completed preparation.
6. In a future supported production integration, use standing authorization within configured limits. Reserve the job durably before any irreversible submit step. This broad authorization path is not implemented or enabled in the current pilot.
7. Count only positive submission confirmation as success. An uncertain click stays pending reconciliation and must not be retried automatically. Stop at the configured cap or window; report a shortfall when insufficient eligible jobs exist.
8. Continue after job-specific blockers, with bounded retries only for safe pre-submission transient failures. Isolate a failing portal. Stop globally for lost browser/state integrity or unavailable controls. Keep reasons and progress so the next run can resume safely.

The implemented queue distinguishes queued, preparing, eligible, prepared, needs input, retry wait, skipped, submission reserved, confirmed and uncertain. The existing ledger is shared with the local backend API and atomic cap reservations. Deterministic and synthetic-browser restart acceptance now passes; live operational acceptance, a visual dashboard and supported standing-authorized production remain pending. Nothing guarantees a portal never changes. The objective is visible, contained failure without lost progress or duplicate applications.

## Implemented in this continuation

- Replaced the scheduled review script's call to the single-submit pilot CLI with a fixed, non-submitting review entry point.
- Scheduled execution reads the live Sheet controls, never requests interactive login/OTP, and restricts unattended sources to explicitly configured public Greenhouse/Lever feeds. Unsupported/browser-only portals fail with a clear reason; they are not silently automated.
- Added an OS-managed lock retained across the worker's exec. Overlapping scheduled workers are refused; a killed worker releases its lock without manual stale-directory deletion.
- Reused the project Python environment, retained explicit interpreter overrides, serialized launchd XML safely, and preserved only allowlisted nonsecret scheduling settings.
- Added CI triggering for script changes and targeted regression checks for launch routing, controls, overlap, crash recovery, configuration failures and XML/path handling.

The default public source lists are empty. Until real employer board/site names and the existing live control bridge are configured, the worker reports a configuration blocker and opens no jobs. This is deliberate configuration validation, not successful discovery or completed applications. No credentials, profile, resume, existing ledger or Sheet values were modified.

Local verification passed: **697 unit tests**, including ten new scheduling regressions; Python compilation, shell syntax and whitespace checks passed. The lock regression executes a separate worker, verifies mutual exclusion across exec, force-terminates it and confirms a subsequent launch can acquire the remaining lock file. The installer test parses generated plist bytes without installing a launchd job. These are local deterministic checks; no real Mac, credential bridge or portal acceptance is claimed. CI status for the final commit is tracked in draft PR #2.

## Remaining acceptance

1. Verify the existing Apps Script bridge from the Mac against the real Sheet without exposing credentials. Connected-Drive access from Work is separate evidence.
2. Select employer targets with eligible current roles and validate one complete non-submitting employer-site form with the exact resume.
3. Streamline the permitted LinkedIn applicant workflow and preserve its existing real-form/resume/Review acceptance work. Do not replace live evidence with fixture totals.
4. Test restart, pause, expired login, changed layouts, cross-source duplicates, unknown required questions, uncertain submission and cap exhaustion. No blind retry after Submit.
5. Only then enable standing-authorized applications on individually supported integrations, start with a bounded pilot, and measure confirmed outcomes before raising limits. Do not promise that a target count will be achieved every day or that every portal can operate without human intervention.

## Official references checked

- [LinkedIn automated activity policy](https://www.linkedin.com/help/linkedin/answer/a1340567/automated-activity-on-linkedin?lang=en)
- [Indeed jobseeker guidelines](https://support.indeed.com/hc/en-in/articles/360028540531-Indeed-Jobseeker-Guidelines)
- [Instahyre candidate matching](https://help.instahyre.com/en/article/what-is-instahyre-1ufln5/)
- [Wellfound remote hiring requirements](https://wellfound.com/candidates/remote)
- [Greenhouse public reads and authenticated submission API](https://docs.greenhouse.io/job-board)
- [Lever postings API scope and limitations](https://github.com/lever/postings-api)
- [Apps Script Properties service](https://developers.google.com/apps-script/guides/properties)
- [Apps Script quotas and runtime limits](https://developers.google.com/apps-script/guides/services/quotas)
