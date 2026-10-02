from dataclasses import dataclass

from application_forms import FillPlan, FormField, build_fill_plan
from browser_portals import inspect_form_snapshot, BrowserFormSnapshot


@dataclass(frozen=True)
class BrowserFieldSnapshot:
    key: str
    label: str
    required: bool
    field_type: str = "text"


def inspect_page_fields(page) -> tuple[BrowserFieldSnapshot, ...]:
    script = """
    () => {
      const controls = Array.from(document.querySelectorAll('input, textarea, select'));
      return controls.map((el, index) => {
        const id = el.id || '';
        let label = '';
        if (id) {
          const explicit = document.querySelector('label[for="' + CSS.escape(id) + '"]');
          if (explicit) label = explicit.innerText || '';
        }
        if (!label) {
          const wrapping = el.closest('label');
          if (wrapping) label = wrapping.innerText || '';
        }
        if (!label) {
          label = el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.name || '';
        }
        return {
          key: el.name || id || ('field_' + index),
          label,
          required: !!el.required || el.getAttribute('aria-required') === 'true',
          field_type: (el.type || el.tagName || 'text').toLowerCase(),
        };
      });
    }
    """
    try:
        raw = page.evaluate(script)
    except Exception:
        return ()

    fields: list[BrowserFieldSnapshot] = []
    for item in raw or []:
        label = str(item.get("label", "")).strip()
        key = str(item.get("key", "")).strip()
        if not key:
            continue
        fields.append(
            BrowserFieldSnapshot(
                key=key,
                label=label,
                required=bool(item.get("required", False)),
                field_type=str(item.get("field_type", "text")),
            )
        )
    return tuple(fields)


def build_page_fill_plan(
    page,
    profile: dict,
    *,
    resume_path: str = "",
    duplicate: bool = False,
    live_submission_enabled: bool = False,
) -> FillPlan:
    fields = inspect_page_fields(page)
    try:
        body_text = page.locator("body").inner_text(timeout=3000)
    except Exception:
        body_text = ""

    captcha = False
    try:
        captcha = page.locator("iframe[src*='recaptcha'], [data-sitekey], .g-recaptcha").count() > 0
    except Exception:
        pass

    form_inspection = inspect_form_snapshot(
        BrowserFormSnapshot(
            body_text=body_text,
            required_field_names=tuple(f.label for f in fields if f.required),
            captcha_selector_found=captcha,
        )
    )

    return build_fill_plan(
        tuple(
            FormField(
                key=f.key,
                label=f.label,
                required=f.required,
                field_type=f.field_type,
            )
            for f in fields
        ),
        profile,
        resume_path=resume_path,
        captcha_present=form_inspection.captcha_present,
        manual_auth_required=form_inspection.manual_auth_required,
        duplicate=duplicate,
        live_submission_enabled=live_submission_enabled,
    )


def apply_fill_plan(page, plan: FillPlan) -> tuple[str, ...]:
    if not plan.can_fill:
        return plan.reasons

    for key, value in plan.values.items():
        selector = f'[name="{key}"], #{key}'
        try:
            target = page.locator(selector).first
            if not target.count():
                continue
            tag = target.evaluate("(el) => el.tagName.toLowerCase()")
            if tag == "select":
                target.select_option(label=value)
            else:
                target.fill(value)
        except Exception:
            continue

    if plan.resume_path:
        try:
            upload = page.locator('input[type="file"]').first
            if upload.count():
                upload.set_input_files(plan.resume_path)
        except Exception:
            return tuple(dict.fromkeys([*plan.reasons, "resume_upload_failed"]))

    return plan.reasons
