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
      const controls = Array.from(document.querySelectorAll('input, textarea, select'))
        .filter((el) => {
          const type = (el.getAttribute('type') || '').toLowerCase();
          return type !== 'hidden' && !el.disabled;
        });

      const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
      const looksRequired = (el, label) => {
        if (el.required || el.getAttribute('aria-required') === 'true') return true;
        if (el.getAttribute('data-required') === 'true') return true;
        if (/\\brequired\\b/i.test(el.getAttribute('class') || '')) return true;
        if (/\\*/.test(label) || /\\(required\\)/i.test(label)) return true;

        const container = el.closest(
          '.form-group, .field, .field-group, .application-field, [data-qa*="field"], [class*="field"]'
        );
        if (container) {
          const marker = container.querySelector(
            '[aria-hidden="true"].required, .required, [class*="required"], [data-required="true"]'
          );
          if (marker && /\\*|required/i.test(clean(marker.textContent) || marker.className || '')) {
            return true;
          }
        }
        return false;
      };

      return controls.map((el, index) => {
        const id = el.id || '';
        let label = '';
        if (id) {
          const explicit = document.querySelector('label[for="' + CSS.escape(id) + '"]');
          if (explicit) label = explicit.innerText || explicit.textContent || '';
        }
        if (!label) {
          const wrapping = el.closest('label');
          if (wrapping) label = wrapping.innerText || wrapping.textContent || '';
        }
        if (!label) {
          label = el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.name || '';
        }
        label = clean(label);
        return {
          key: el.name || id || ('field_' + index),
          label,
          required: looksRequired(el, label),
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
    fill_failures: list[str] = []

    if not plan.can_fill:
        return tuple(dict.fromkeys([*plan.reasons, *fill_failures]))

    for key, value in plan.values.items():
        selector = f'[name="{key}"], #{key}'
        try:
            target = page.locator(selector).first
            if not target.count():
                fill_failures.append(f"field_not_found:{key}")
                continue

            tag = target.evaluate("(el) => el.tagName.toLowerCase()")
            input_type = (target.get_attribute("type") or "").lower()

            if tag == "select":
                target.select_option(label=value)

            elif input_type == "radio":
                options = page.locator(f'input[type="radio"][name="{key}"]')
                wanted = value.strip().lower()
                matched = False

                for index in range(options.count()):
                    option = options.nth(index)
                    option_value = (option.get_attribute("value") or "").strip().lower()
                    option_id = option.get_attribute("id") or ""
                    option_label = ""

                    if option_id:
                        try:
                            option_label = page.locator(
                                f'label[for="{option_id}"]'
                            ).first.inner_text(timeout=1000).strip().lower()
                        except Exception:
                            option_label = ""

                    if wanted not in {option_value, option_label}:
                        continue

                    matched = True
                    checked = False

                    try:
                        option.check(force=True, timeout=2000)
                        checked = option.is_checked()
                    except Exception:
                        checked = False

                    if not checked and option_id:
                        try:
                            label = page.locator(f'label[for="{option_id}"]').first
                            if label.count():
                                label.click(force=True, timeout=2000)
                                checked = option.is_checked()
                        except Exception:
                            checked = False

                    if not checked:
                        try:
                            option.click(force=True, timeout=2000)
                            checked = option.is_checked()
                        except Exception:
                            checked = False

                    if not checked:
                        fill_failures.append(f"radio_not_selected:{key}:{value}")
                    break

                if not matched:
                    fill_failures.append(f"radio_option_not_found:{key}:{value}")

            else:
                target.fill(value)

        except Exception as exc:
            fill_failures.append(f"field_fill_failed:{key}:{type(exc).__name__}")

    if plan.resume_path:
        try:
            upload = page.locator('input[type="file"]').first
            if upload.count():
                upload.set_input_files(plan.resume_path)
        except Exception:
            return tuple(dict.fromkeys([*plan.reasons, "resume_upload_failed"]))

    return plan.reasons
