# Test Plan

## Authentication
- Existing session accepted.
- Expired session detected.
- Email OTP accepted only when recent, sender/context match the portal login, and value is not logged.
- Authenticator app, CAPTCHA, security key or biometric pauses for human action.
- Credentials/cookies never appear in repository or CI logs.

## Search and matching
- Target-role query is applied.
- Location/remote preferences are respected.
- Seniority and experience mismatch are blocked.
- Sponsorship policy is enforced.
- Duplicate job/application is blocked.

## Application
- Supported form is detected.
- Known truthful fields may be filled.
- Unknown required fields stop submission.
- Resume upload is validated before submit.
- CAPTCHA/manual auth stops automation.
- Live submission flag must be enabled.
- Daily cap and duplicate guard are enforced before controlled live release.

## Failure handling
- Portal layout change fails closed.
- Network error does not create duplicate submission.
- Session expiry returns to login state.
- Audit record is produced without secrets.
