import argparse
import json
import time
from pathlib import Path


def _load_json(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _tail_jsonl(path: Path, limit: int):
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    result = []
    for line in lines[-max(limit, 0):]:
        try:
            result.append(json.loads(line))
        except Exception:
            continue
    return result


def _suggest(reason: str) -> str:
    value = (reason or "").lower()
    rules = (
        ("captcha", "Human action required: complete the CAPTCHA, then rerun the blocked job."),
        ("checkpoint", "Human action required: LinkedIn security checkpoint/MFA must be completed manually."),
        ("unknown_required", "A mandatory application fact is unknown. Add a verified answer to the private profile; do not guess."),
        ("radio_option_not_found", "Observed radio options did not safely match the verified answer. Inspect option labels before changing matching logic."),
        ("review_mismatch", "Review values differ from the verified profile. Inspect the reported field before submission."),
        ("next_no_transition", "The portal did not prove a page transition after Next/Continue. Selector or transition detection needs updating."),
        ("application_entry_not_found", "The application entry control was not detected. Check whether the job is closed or the portal selector changed."),
        ("form_not_ready", "The application entry opened, but a supported form was not detected. Inspect the external ATS layout/selectors."),
        ("application_page_open_failed", "External ATS navigation failed. Check redirect, timeout, authentication, or unsupported provider."),
        ("field_not_found", "A planned form field could not be located. Update field aliases/selectors using the observed label."),
        ("field_fill_failed", "A known field was found but could not be filled. Inspect control type and post-fill verification."),
        ("resume_upload_failed", "Resume upload failed. Verify file control, accepted type, and local file path."),
        ("score_below_threshold", "No defect: the job scored below the configured application threshold."),
        ("recent_similar_application", "No defect: the 90-day same/similar-role cooldown blocked a duplicate application."),
    )
    for marker, recommendation in rules:
        if marker in value:
            return recommendation
    if reason:
        return "Inspect the latest trace events around this blocker; no safe automatic fix is mapped yet."
    return ""


def _stuck_hint(step: str, elapsed: float) -> str:
    if elapsed < 15:
        return ""
    value = (step or "").lower()
    if "navigation_commit" in value or "search_navigation" in value:
        return "Possible stall: browser navigation/redirect/network. Check the current URL and portal response."
    if "navigation_dom_ready" in value:
        return "Possible stall: page committed but DOM readiness is slow. The bounded navigation timeout should recover automatically."
    if "application_entry" in value:
        return "Possible stall: waiting for an Apply/Easy Apply/application-entry control. Portal selectors or a closed job may be involved."
    if "external_apply_navigation" in value:
        return "Possible stall: external ATS redirect/navigation. The ATS may be slow, blocked, or require authentication."
    if "external_form_inspection" in value:
        return "Possible stall: external ATS loaded but the application form structure is not being recognized."
    if "form_plan_build" in value:
        return "Possible stall: application form inspection/mapping. A complex or dynamic field may be blocking inspection."
    if "form_fill" in value:
        return "Possible stall: filling or verifying a form control. Inspect the latest field-related trace event."
    if "next_transition" in value:
        return "Possible stall: Next/Continue was clicked but page transition has not been proven."
    if "review" in value:
        return "Possible stall: review page validation or review control detection."
    if step:
        return "Possible stall: this step has been active unusually long. Inspect the latest trace events below."
    return ""


def _print_snapshot(base_dir: Path, tail: int):
    status_path = base_dir / "agent_status.json"
    latest_path = base_dir / "agent_latest.jsonl"
    report_path = base_dir / "review_ready_report.json"

    status = _load_json(status_path)
    print("=== AGENT STATUS ===")
    if not status:
        print("No agent status has been recorded yet.")
    else:
        for key in (
            "run_id",
            "status",
            "pid",
            "current_step",
            "step_path",
            "step_elapsed_seconds",
            "run_elapsed_seconds",
            "last_event",
            "last_event_at",
            "events_file",
        ):
            print(f"{key}: {status.get(key, '')}")
        hint = _stuck_hint(
            str(status.get("current_step", "") or ""),
            float(status.get("step_elapsed_seconds", 0) or 0),
        )
        if hint:
            print(f"possible_stall: {hint}")

    report = _load_json(report_path)
    outcomes = report.get("outcomes", []) if isinstance(report, dict) else []
    blockers = [
        item for item in outcomes
        if str(item.get("status", "")).upper() not in {
            "READY_FOR_REVIEW",
            "SKIPPED_UNQUALIFIED",
            "SKIPPED_DUPLICATE",
            "SKIPPED_INELIGIBLE",
            "SKIPPED_JD",
        }
    ]
    print("\n=== LAST RUN BLOCKERS ===")
    if not blockers:
        print("No blocking outcomes recorded.")
    else:
        for item in blockers:
            reason = str(item.get("reason", "") or "")
            print(f"- {item.get('job_key', '')}: {item.get('status', '')}")
            print(f"  reason: {reason}")
            suggestion = _suggest(reason)
            if suggestion:
                print(f"  suggested_fix: {suggestion}")

    print(f"\n=== LAST {tail} TRACE EVENTS ===")
    events = _tail_jsonl(latest_path, tail)
    if not events:
        print("No trace events recorded.")
    for event in events:
        print(json.dumps(event, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect or follow the local Job AI Agent trace.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--tail", type=int, default=25)
    parser.add_argument("--follow", action="store_true")
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()

    base_dir = Path(args.data_dir)
    if not args.follow:
        _print_snapshot(base_dir, args.tail)
        return 0

    last_signature = None
    try:
        while True:
            status = _load_json(base_dir / "agent_status.json")
            signature = (
                status.get("run_id"),
                status.get("last_event_at"),
                status.get("current_step"),
                status.get("status"),
            )
            if signature != last_signature:
                print("\033[2J\033[H", end="")
                _print_snapshot(base_dir, args.tail)
                last_signature = signature
            if status and status.get("status") not in {"", "running"}:
                return 0
            time.sleep(max(args.interval, 0.5))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
