import argparse
import json

from models import Job
from runner import discover_from_config, evaluate_jobs, load_profile
from store import JobStore


DEMO_JOBS = [
    Job(
        source="demo",
        external_id="1",
        company="ExampleCo",
        title="Customer Success Manager",
        location="Remote - India",
        url="https://example.invalid/jobs/1",
        description="Customer success role requiring SLA, incident management, stakeholder management and 5+ years of experience.",
        required_skills=("customer success", "sla", "incident management", "stakeholder management"),
        minimum_years=5,
        remote=True,
    ),
    Job(
        source="demo",
        external_id="2",
        company="ExampleCo",
        title="Enterprise Sales Director",
        location="New York, United States",
        url="https://example.invalid/jobs/2",
        description="Sales leadership role. We will not sponsor employment visas.",
        required_skills=("account management",),
        minimum_years=10,
        remote=False,
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Zero-cost job-agent dry-run evaluator")
    parser.add_argument("--profile", default="config/sample_profile.json")
    parser.add_argument("--sources", default="config/sources.example.json")
    parser.add_argument("--db", default="data/jobs.db")
    parser.add_argument("--audit", default="data/decisions.csv")
    parser.add_argument("--threshold", type=int, default=75)
    parser.add_argument("--demo", action="store_true", help="Use offline demo jobs; no network calls")
    args = parser.parse_args()

    profile = load_profile(args.profile)
    taxonomy = profile.skill_taxonomy or profile.skills
    jobs = DEMO_JOBS if args.demo else discover_from_config(args.sources, taxonomy)
    summary = evaluate_jobs(jobs, profile, args.threshold, JobStore(args.db), args.audit)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
