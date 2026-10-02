# Release Checklist

A portal cannot enter controlled live mode until all items pass:

- Login works with user-owned session.
- Session expiry and re-login are handled.
- OTP flow is scoped, recent, and redacted.
- Search returns target-role jobs.
- Matching policy passes QA.
- Form inspector identifies all required fields.
- Resume upload validated.
- Unknown required answers stop automation.
- CAPTCHA/manual MFA stop automation.
- Duplicate guard verified.
- Audit record contains no secrets.
- Live submission defaults OFF.
- Daily limit configured.
- Zero-cost check passes.
- Portal-specific smoke test passes.
- Main branch remains untouched until explicit approval.
