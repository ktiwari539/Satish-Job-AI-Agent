# Zero-Cost Guard

The project must operate with no paid AI/API or cloud dependency during QA.

Allowed:
- Public read-only job feeds.
- Local Python/browser execution.
- Free CI where available under the repository/account plan.
- User-owned email OAuth connection for OTP retrieval when available without additional paid service.

Blocked by design:
- Paid model/API calls.
- Paid proxy/captcha-solving services.
- Paid cloud runners or VMs.
- Any automatic upgrade or paid subscription.

Any feature that introduces cost must be disabled by default and reviewed before adoption.
