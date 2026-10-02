# Risk Register

| Risk | Impact | Control |
|---|---|---|
| Credential/session leak | Critical | Never store in repo; encrypted local/private-runner storage only |
| OTP leakage | High | Runtime only; redact from logs and audit |
| CAPTCHA/bot challenge | High | Stop and request human action; no bypass |
| Portal layout change | High | Adapter isolation and fail-closed inspection |
| Duplicate applications | High | Persistent application/job key before submit |
| Wrong/unknown answer | High | Truthful-known-answer rule; human approval otherwise |
| Account restriction | High | Conservative pacing, portal-specific QA, no brittle mass actions |
| Paid-service drift | Medium | Zero-cost CI guard and no paid dependency |
| Public-repo personal data | Critical | Synthetic QA profile only; real profile kept outside repo |
| Accidental live submit | Critical | Global live flag off plus portal-specific release gate |
