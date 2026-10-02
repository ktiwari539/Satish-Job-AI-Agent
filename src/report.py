import argparse
import csv
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Print explainable QA summary from a dry-run audit CSV")
    parser.add_argument("--audit", required=True)
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()

    rows = list(csv.DictReader(Path(args.audit).open(encoding="utf-8")))
    qualified = [r for r in rows if r["final_decision"] == "QUALIFIED_DRY_RUN"]
    qualified.sort(key=lambda r: int(r["score"]), reverse=True)

    print(f"QA_REPORT total={len(rows)} qualified={len(qualified)} skipped={len(rows)-len(qualified)}")
    print("score | role | skill | exp | company | title | location | matched | missing")
    for row in qualified[: args.limit]:
        print(
            f'{row["score"]} | {row["role_score"]} | {row["skill_score"]} | '
            f'{row["experience_score"]} | {row["company"]} | {row["title"]} | '
            f'{row["location"]} | {row["matched_skills"]} | {row["missing_skills"]}'
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
