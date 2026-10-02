# Satish Job AI Agent

Zero-cost, dry-run-first job discovery and matching automation.

## Current phase: Match Quality V2

The agent currently performs read-only discovery and explainable deterministic matching. It does **not** submit applications.

### Safety rules
- No OpenAI API or other paid model API
- No paid cloud runner
- No live job submission in test mode
- No credentials, cookies, CV, phone, email, or other personal data committed
- Public ATS discovery is read-only
- GitHub Actions is used only for CI/testing

### Match Quality V2
- Target-role relevance gate
- Blocked unrelated title families
- Independent job-skill taxonomy for visible skill gaps
- Experience-fit scoring and hard gap protection
- India/remote location policy
- Sponsorship policy
- SQLite duplicate guard
- Explainable CSV audit + top-job QA report

### Supported discovery adapters
- Greenhouse public job boards
- Lever public postings

### Branch policy
- `main`: controlled baseline
- `test/job-ai-agent-zero-cost`: development and QA

There is intentionally no form-filling or submission module yet. That is the next release gate after matching QA passes.
