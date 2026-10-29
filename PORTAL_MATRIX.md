# Portal readiness matrix

The target is autonomous discovery, qualification, verified form preparation and approved submission across portals. A registered portal or passing fixture is not a certified live adapter.

The user has confirmed LinkedIn login in the agent browser and Naukri/Indeed login in ordinary Chrome. Actual user exports establish one Naukri posting with a 905-character JD and one Indeed posting with a 7,147-character JD, each with correlated Apply controls. On 29 October the applicant authorized REVIEW preparation and worldwide discovery; connected-Sheet edits/readback reconciled the authorization row and mode dropdown. The existing resume is now accessible from Drive with local integrity checks. A read-only evaluation of both accepted captures stopped for missing work locations; Naukri also has insufficient skill evidence. These are not opened forms or ready applications. Bounded batches and optional Indeed access setup remain available but live batch acceptance is pending. See [live capture checkpoint](docs/LIVE_CAPTURE_CHECKPOINT.md). Automatic Chrome applications remain unimplemented/unverified. Apps Script project/manifest exists but its direct agent bridge connection remains unverified; connected-Sheet readback is a separate path. Unknown JS/SSO/signup layouts still block.

| Portal | Discovery | Preparation | Actual live acceptance | Submission |
| --- | --- | --- | --- | --- |
| LinkedIn | Browser cards and exact job IDs | Modal/inline Easy Apply; verified answers, identity, selected resume and Review checks | Mac login confirmed; six JDs read historically; new resume/Review acceptance pending | Separate exact-job approval and durable reservation required |
| Naukri | Browser cards; ordinary-Chrome current-tab and batch export | Fixture-tested native forms; ordinary-Chrome capture/inspection only | One real full-posting JD and exact-job Apply control captured; form/resume/Review still pending | Native one-click/custom flows remain gated |
| Indeed | Browser cards, current-tab and optional full-JD batch; `jk`/`vjk` retained | Fixture-tested native forms; ordinary-Chrome capture/inspection only | Actual 0.6.3 export: one 7,147-character JD and exact-job Apply control; form/resume/Review pending | Unverified entry/submission adapter remains gated |
| Greenhouse | Configured public board feeds | Verified native form pages | Pending | Not live-certified |
| Lever | Configured public site feeds | Verified native form pages; landing-page entry variants remain gated | Pending | Not live-certified |
| Workday | Company-specific target and JD selectors | Adapter-specific work pending | Pending | Disabled |
| Foundit, Instahyre, Cutshort, Wellfound, Hirist, Glassdoor | Registered search routes; some JD selectors | Live discovery and application adapters pending | Pending | Disabled |

Shared checks include full visible JD extraction, target role/skills/experience matching, eligibility, confirmed-application dedupe, cross-portal duplicate preparation suppression within a batch, truthful answers, form readback, matching name/email/phone, resume provenance and current attachment evidence. The broader runner reports unsupported adapters explicitly and continues to another job/portal after a job-specific blocker. A global browser failure stops the run and preserves completed evidence.

Preparation history suppresses unchanged blocked/ready forms for 24 hours across runs. Changes to verified facts, resume, job details, runtime or relevant code invalidate this cooldown. It is separate from confirmed-application dedupe and never records a preparation as submitted.

`READY_FOR_REVIEW` is not proof of submission, release acceptance or permission to click Submit. Unknown applicant facts are never guessed. CAPTCHA/OTP/authentication and unverified one-click Apply controls remain explicit blockers. No new live submissions were enabled by the multi-portal preparation workflow.

For portals with verified agent-browser sessions, the bounded preparation workflow is available from the project folder. For the current Naukri/Indeed Google rejection, use the ordinary-Chrome checkpoint above; repeating setup does not change that restriction.

```bash
bash scripts/certify_portals.sh --setup --portals linkedin,naukri,indeed --max-jobs 10
```

The public qualification profile supplies the target role when `--query` is omitted. Each portal considers at most 20 jobs; the default is 10. `--portals all` reports every registered portal's current adapter status. Configured Greenhouse/Lever feeds can be added with `--portals linkedin,naukri,indeed,greenhouse,lever --sources config/sources.example.json`; configure real target board/site names locally first. Public feed failures are isolated by board/site and portal.

Read `data/certification/portals.json` for counts, per-job cross-checks and referenced structural blocker reports. Real-world acceptance is still required separately for each portal and layout.
