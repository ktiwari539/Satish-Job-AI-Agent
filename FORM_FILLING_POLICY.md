# Form Filling Policy

## Fill-only QA

The browser may fill an application form only when:
- the field maps to an approved profile attribute,
- the value exists in the private runtime profile,
- no CAPTCHA or manual authentication challenge is active,
- resume upload points to an existing PDF/DOC/DOCX,
- and no fabricated answer is needed.

Unknown optional fields are left blank.
Unknown required fields stop submission and are surfaced for human review.

## Never auto-answer without an explicit stored fact

Examples:
- salary expectations,
- notice period,
- sponsorship/work authorization,
- relocation willingness,
- demographic/self-identification questions,
- legal attestations,
- security clearance,
- background-check consent,
- custom employer screening questions.

Some of these may be fillable once a user-approved value exists in the private profile, but the agent must not infer them.

## Submit

`live_submission_enabled` remains false in QA. A fully valid fill plan still cannot submit until controlled-live approval is explicitly enabled.
