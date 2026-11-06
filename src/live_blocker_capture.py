"""Privacy-safe local Easy Apply diagnostics captured before Chromium closes.

No user-entered values, page HTML, screenshots, credentials, or names from
form labels are collected. Never click or change the page in this module.
"""
import json
import time
from pathlib import Path

from agent_trace import get_active_tracer, trace_event


# No full-body text, form values, visible labels, URLs or element HTML.
# Return only count/booleans and whitelisted control kinds.
_SNAPSHOT_SCRIPT = r"""() => {
  const count = (selector) => {
    try { return Math.min(document.querySelectorAll(selector).length, 200); }
    catch { return 0; }
  };
  const visible = el => {
    if (!el || !el.isConnected) return false;
    const r = el.getBoundingClientRect(), st = getComputedStyle(el);
    return r.width > 0 && r.height > 0 &&
      st.display !== 'none' && st.visibility !== 'hidden';
  };
  const all = selector => {
    try { return [...document.querySelectorAll(selector)].slice(0, 250); }
    catch { return []; }
  };
  const dialogs = all('.jobs-easy-apply-modal,.artdeco-modal,[role="dialog"]');
  const active = dialogs.filter(visible);
  const body = document.body;
  const bodyText = String(body?.innerText || '');
  const matches = [...bodyText.matchAll(/\b(\d{1,2})\s*\/\s*(\d{1,2})\s*pages?\b/gi)];
  const progress = matches.length ? matches[matches.length - 1][1] + '/' + matches[matches.length - 1][2] : '';
  const inputs = all('input,textarea,select');
  const isPhone = el => {
    const fields = [
      el.getAttribute('name') || '', el.getAttribute('id') || '',
      el.getAttribute('autocomplete') || '', el.getAttribute('type') || ''
    ].join(' ').toLowerCase();
    return /(phone|mobile|telephone|contact.?number|tel[-_]?number)/.test(fields) ||
      el.getAttribute('type') === 'tel';
  };
  const inputMeta = el => ({
    kind: el.tagName.toLowerCase(),
    input_type: ['tel','text','email','number','checkbox','radio','file','password','hidden']
      .includes(String(el.getAttribute('type') || '').toLowerCase())
      ? String(el.getAttribute('type') || '').toLowerCase() : 'other',
    visible: visible(el),
    required: !!(el.required || el.getAttribute('aria-required') === 'true'),
    empty: String(el.value || '').length === 0,
    invalid: el.getAttribute('aria-invalid') === 'true' ||
      (!!el.validity && el.validity.valid === false),
    disabled: !!el.disabled,
  });
  const phone = inputs.filter(isPhone).slice(0, 12).map(inputMeta);
  const controls = all('button,[role="button"],input[type="button"],input[type="submit"]');
  const normalize = el => String(
    el.getAttribute('aria-label') || el.innerText || el.textContent ||
    el.getAttribute('value') || ''
  ).replace(/\s+/g,' ').trim().toLowerCase();
  const actions = [
    ['next', ['next', 'next step', 'continue', 'continue to next step']],
    ['review', ['review', 'review application', 'review your application']],
    ['submit', ['submit', 'submit application', 'send application']],
    ['back', ['back', 'previous']],
  ].map(([name, names]) => {
    const matching = controls.filter(el => names.includes(normalize(el)));
    return {
      action: name, matched: Math.min(matching.length, 50),
      visible: matching.filter(visible).length,
      enabled: matching.filter(el => visible(el) && !el.disabled &&
        el.getAttribute('aria-disabled') !== 'true').length,
      within_modal: active.length
        ? matching.filter(el => active.some(root => root.contains(el))).length : 0
    };
  });
  const validation = {
    invalid_visible: inputs.filter(el => visible(el) && (
      el.getAttribute('aria-invalid') === 'true' ||
      (el.validity && el.validity.valid === false)
    )).length,
    required_empty_visible: inputs.filter(el => visible(el) &&
      (el.required || el.getAttribute('aria-required') === 'true') &&
      String(el.value || '').length === 0).length,
    known_required_warning: /this field is required|please enter a valid|please provide a valid/i.test(bodyText),
  };
  return {
    progress, visible_modal_count: active.length,
    dialog_nodes: dialogs.length, form_nodes: count('form'),
    body_chars: Math.min(bodyText.length, 100000),
    input_count: inputs.length, phone, actions, validation,
    main_frame: window === window.top,
  };
}"""


def _safe_snapshot(payload):
    """Whitelist and type-validate the browser's response before writing."""
    if not isinstance(payload, dict):
        return {"availability": "browser_probe_failed"}
    safe = {}
    progress = payload.get("progress")
    if isinstance(progress, str) and len(progress) <= 5:
        if all(c.isdigit() or c == "/" for c in progress):
            safe["progress"] = progress
    for key in ("visible_modal_count", "dialog_nodes", "form_nodes", "body_chars", "input_count"):
        val = payload.get(key)
        safe[key] = min(max(val, 0), 100000) if type(val) is int else 0
    safe["main_frame"] = payload.get("main_frame") is True
    phones = []
    for obj in (payload.get("phone") or [])[:12]:
        if not isinstance(obj, dict):
            continue
        phones.append({
            "visible": obj.get("visible") is True,
            "required": obj.get("required") is True,
            "empty": obj.get("empty") is True,
            "invalid": obj.get("invalid") is True,
            "disabled": obj.get("disabled") is True,
        })
    safe["phone"] = phones
    actions = []
    for obj in (payload.get("actions") or [])[:4]:
        if not isinstance(obj, dict) or obj.get("action") not in ("next", "review", "submit", "back"):
            continue
        action = {"action": obj["action"]}
        for field in ("matched", "visible", "enabled", "within_modal"):
            val = obj.get(field)
            action[field] = min(max(val, 0), 250) if type(val) is int else 0
        actions.append(action)
    safe["actions"] = actions
    raw_validation = payload.get("validation") or {}
    if not isinstance(raw_validation, dict):
        raw_validation = {}
    safe["validation"] = {
        key: min(max(raw_validation.get(key, 0), 0), 250)
        if type(raw_validation.get(key)) is int else 0
        for key in ("invalid_visible", "required_empty_visible")
    }
    safe["validation"]["known_required_warning"] = raw_validation.get("known_required_warning") is True
    return safe


def inspect_easy_apply_state(page, *, stage: str, step_index=None):
    """Emits only safe DOM observations for before/after step comparison."""
    try:
        raw = page.evaluate(_SNAPSHOT_SCRIPT)
    except Exception:
        raw = None
    result = _safe_snapshot(raw)
    trace_event("easy_apply_state_snapshot", stage=stage, step_index=step_index,
                snapshot=result)
    return result


def _safe_identifier(value):
    """No human-authored error message or applicant name in blocker reports."""
    import re
    candidate = str(value or "")
    return candidate[:80] if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,79}", candidate) else "unclassified"


def capture_blocker(page, *, stage, outcome, reason_code="", steps_completed=0):
    """Always persist blocker evidence while the page is still open."""
    data = inspect_easy_apply_state(page, stage="blocked")
    tracer = get_active_tracer()
    record = {
        "status": "application_blocker_captured",
        "stage": _safe_identifier(stage),
        "outcome": _safe_identifier(outcome),
        "reason_code": _safe_identifier(str(reason_code).split(":", 1)[0]),
        "steps_completed": max(0, int(steps_completed or 0)),
        "snapshot": data,
        "run_id": tracer.run_id if tracer is not None else "",
    }
    location = ""
    if tracer is not None:
        try:
            # A multi-job queue shares one tracer. Preserve every candidate's
            # evidence rather than overwriting all earlier blocker reports.
            path = Path(tracer.trace_dir) / (tracer.run_id + "." + str(time.monotonic_ns()) + ".blocker.json")
            path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
            location = str(path)
        except (OSError, ValueError):
            pass
    trace_event("application_blocker_captured", stage=record["stage"],
                outcome=record["outcome"], reason_code=record["reason_code"],
                steps_completed=record["steps_completed"], report_path=location,
                snapshot=data)
    return location


def hold_blocked_browser(page, seconds):
    """Keep Chromium visible without leaving a Playwright command pending.

    Python's own sleep is interrupted by Ctrl-C without spawning an
    unawaited Playwright Page.wait_for_timeout coroutine on shutdown.
    """
    duration = max(0, min(int(seconds or 0), 120))
    if duration == 0:
        return
    trace_event("blocked_browser_hold_start", seconds=duration)
    try:
        time.sleep(duration)
    except KeyboardInterrupt:
        trace_event("blocked_browser_hold_interrupted", error_type="KeyboardInterrupt")
        raise
