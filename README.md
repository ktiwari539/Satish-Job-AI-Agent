# Satish Job AI Agent

Zero-cost, dry-run-first job discovery and matching automation.

## Safety rules

- No OpenAI API or other paid model API
- No paid cloud runner
- No live job submission in test mode
- No credentials, cookies, CV, phone, email, or other personal data committed
- Public ATS discovery is read-only
- GitHub Actions is used only for CI/testing

## Architecture

Public ATS listings -> normalization -> deterministic matching -> eligibility checks -> duplicate guard -> CSV audit log

Supported read-only discovery adapters:
- Greenhouse public job boards
- Lever public postings

## Branch policy

- main: controlled baseline
- test/job-ai-agent-zero-cost: development and QA

## Offline smoke test

python src/cli.py --demo --profile config/sample_profile.json --db /tmp/job-agent.db --audit /tmp/job-agent.csv

## Public read-only discovery smoke test

python src/cli.py --profile config/sample_profile.json --sources config/sources.qa.json --db /tmp/job-agent-public.db --audit /tmp/job-agent-public.csv

There is intentionally no application submission module in this test branch.
