# Portal readiness matrix

The target is autonomous discovery, qualification, verified form preparation and approved submission across portals. A registered portal or passing fixture is not a certified live adapter.

The 27 October update connects configured login and email-code handling for supported native LinkedIn/Naukri/Indeed forms. Apps Script source and client are prepared; the user's deployed script contract and actual mailbox/login behavior remain unverified. See [authentication and JD checkpoint](docs/AUTH_AND_JD_CHECKPOINT.md). Unknown JS/SSO/signup layouts still block.

| Portal | Discovery | Preparation | Actual live acceptance | Submission |
| --- | --- | --- | --- | --- |
| LinkedIn | Browser cards and exact job IDs | Modal/inline Easy Apply; verified answers, identity, selected resume and Review checks | Historical partial evidence; current Mac startup blocked | Separate exact-job approval and durable reservation required |
| Naukri | Browser cards; existing regular-browser export tooling | Verified visible native forms; employer/eligibility gates; unsupported Apply entries block | Pending | Native one-click/custom flows remain gated |
| Indeed | Browser cards; `jk`/`vjk` identity retained | Verified visible native forms | Pending | Unverified entry/submission adapter remains gated |
| Greenhouse | Configured public board feeds | Verified native form pages | Pending | Not live-certified |
| Lever | Configured public site feeds | Verified native form pages; landing-page entry variants remain gated | Pending | Not live-certified |
| Workday | Company-specific target and JD selectors | Adapter-specific work pending | Pending | Disabled |
| Foundit, Instahyre, Cutshort, Wellfound, Hirist, Glassdoor | Registered search routes; some JD selectors | Live discovery and application adapters pending | Pending | Disabled |

Shared checks include full visible JD extraction, target role/skills/experience matching, eligibility, confirmed-application dedupe, cross-portal duplicate preparation suppression within a batch, truthful answers, form readback, matching name/email/phone, resume provenance and current attachment evidence. The broader runner reports unsupported adapters explicitly and continues to another job/portal after a job-specific blocker. A global browser failure stops the run and preserves completed evidence.

Preparation history suppresses unchanged blocked/ready forms for 24 hours across runs. Changes to verified facts, resume, job details, runtime or relevant code invalidate this cooldown. It is separate from confirmed-application dedupe and never records a preparation as submitted.

`READY_FOR_REVIEW` is not proof of submission, release acceptance or permission to click Submit. Unknown applicant facts are never guessed. CAPTCHA/OTP/authentication and unverified one-click Apply controls remain explicit blockers. No new live submissions were enabled by the multi-portal preparation workflow.

Run the bounded preparation workflow from the project folder:

```bash
bash scripts/certify_portals.sh --setup --portals linkedin,naukri,indeed --max-jobs 10
```

The public qualification profile supplies the target role when `--query` is omitted. Each portal considers at most 20 jobs; the default is 10. `--portals all` reports every registered portal's current adapter status. Configured Greenhouse/Lever feeds can be added with `--portals linkedin,naukri,indeed,greenhouse,lever --sources config/sources.example.json`; configure real target board/site names locally first. Public feed failures are isolated by board/site and portal.

Read `data/certification/portals.json` for counts, per-job cross-checks and referenced structural blocker reports. Real-world acceptance is still required separately for each portal and layout.
