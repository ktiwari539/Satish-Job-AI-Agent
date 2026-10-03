import argparse

from models import Job
from store import JobStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record a manually submitted application in local state.")
    parser.add_argument("--db", default="data/jobs.db")
    parser.add_argument("--source", required=True)
    parser.add_argument("--external-id", required=True)
    parser.add_argument("--company", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--method", default="manual")
    parser.add_argument("--note", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    job = Job(
        source=args.source,
        external_id=args.external_id,
        company=args.company,
        title=args.title,
        location="",
        url=args.url,
        description="",
    )
    store = JobStore(args.db)
    store.mark_applied(job, application_method=args.method, note=args.note)
    print(
        f"APPLIED recorded: {job.source}:{job.external_id} | "
        f"{job.company} | {job.title}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
