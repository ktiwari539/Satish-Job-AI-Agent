from dataclasses import dataclass

from agent_trace import trace_event
from application_forms import FillPlan, FormField, build_fill_plan
from browser_portals import inspect_form_snapshot, BrowserFormSnapshot


@dataclass(frozen=True)
class BrowserFieldSnapshot:
    key: str
    label: str
    required: bool
    field_type: str = "text"
    options: tuple[str, ...] = ()


def inspect_page_fields(page) -> tuple[BrowserFieldSnapshot, ...]:
    script = """
    () => {
      const isVisible = el => {
        if (!el || !el.isConnected) return false;
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 &&
          style.display !== 'none' && style.visibility !== 'hidden';
      };
      // Scope LinkedIn fields to the active modal, including artdeco
      // dialogs without role='dialog'. Otherwise background search fields
      // were falsely interpreted as application fields.
      const dialog = Array.from(document.querySelectorAll(
        '.jobs-easy-apply-modal, .artdeco-modal, [role="dialog"]'
      )).find(isVisible);
      const root = dialog || document;
      const controls = Array.from(root.querySelectorAll('input, textarea, select'))
        .filter((el) => {
          const type = (el.getAttribute('type') || '').toLowerCase();
          return type !== 'hidden' && !el.disabled && !el.readOnly;
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
          const labelledBy = (el.getAttribute('aria-labelledby') || '').trim();
          if (labelledBy) {
            label = labelledBy
              .split(/\s+/)
              .map((token) => {
                const node = document.getElementById(token);
                return node ? (node.innerText || node.textContent || '') : '';
              })
              .filter(Boolean)
              .join(' ');
          }
        }
        if (!label) {
          const container = el.closest(
            '.fb-dash-form-element, .jobs-easy-apply-form-section__grouping, .artdeco-text-input, [class*="form-element"], [class*="form-group"]'
          );
          if (container) {
            const candidate = container.querySelector(
              'label, legend, .fb-dash-form-element__label, [class*="label"]'
            );
            if (candidate) label = candidate.innerText || candidate.textContent || '';
          }
        }
        if (!label) {
          label = el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.name || '';
        }
        label = clean(label);
        const fieldType = (el.type || el.tagName || 'text').toLowerCase();
        let options = [];

        if (el.tagName.toLowerCase() === 'select') {
          options = Array.from(el.options || [])
            .map((option) => clean(option.textContent || option.label || option.value || ''))
            .filter(Boolean);
        } else if (fieldType === 'radio') {
          const name = (el.getAttribute('name') || '').trim();
          const group = name
            ? Array.from(root.querySelectorAll('input[type="radio"][name="' + CSS.escape(name) + '"]'))
            : [el];
          options = group.map((radio) => {
            const radioId = radio.id || '';
            let optionLabel = '';
            if (radioId) {
              const explicit = root.querySelector('label[for="' + CSS.escape(radioId) + '"]') ||
                document.querySelector('label[for="' + CSS.escape(radioId) + '"]');
              if (explicit) optionLabel = explicit.innerText || explicit.textContent || '';
            }
            if (!optionLabel) {
              const wrapping = radio.closest('label');
              if (wrapping) optionLabel = wrapping.innerText || wrapping.textContent || '';
            }
            if (!optionLabel) optionLabel = radio.value || '';
            return clean(optionLabel);
          }).filter(Boolean);
        }

        return {
          key: el.name || id || ('field_' + index),
          label,
          required: looksRequired(el, label),
          field_type: fieldType,
          options,
        };
      });
    }
    """
    try:
        raw = page.evaluate(script)
    except Exception:
        return ()

    merged: dict[str, BrowserFieldSnapshot] = {}
    order: list[str] = []
    for item in raw or []:
        label = str(item.get("label", "")).strip()
        key = str(item.get("key", "")).strip()
        if not key:
            continue
        options = tuple(
            dict.fromkeys(
                str(value).strip()
                for value in (item.get("options") or [])
                if str(value).strip()
            )
        )
        current = BrowserFieldSnapshot(
            key=key,
            label=label,
            required=bool(item.get("required", False)),
            field_type=str(item.get("field_type", "text")),
            options=options,
        )
        if key not in merged:
            merged[key] = current
            order.append(key)
            continue

        previous = merged[key]
        merged[key] = BrowserFieldSnapshot(
            key=key,
            label=previous.label or current.label,
            required=previous.required or current.required,
            field_type=previous.field_type or current.field_type,
            options=tuple(dict.fromkeys((*previous.options, *current.options))),
        )

    return tuple(merged[key] for key in order)


def build_page_fill_plan(
    page,
    profile: dict,
    *,
    resume_path: str = "",
    duplicate: bool = False,
    live_submission_enabled: bool = False,
) -> FillPlan:
    fields = inspect_page_fields(page)
    trace_event(
        "form_snapshot",
        field_count=len(fields),
        fields=[
            {
                # Metadata only. Select options may contain the applicant's
                # email; resume buttons/labels may contain private filenames.
                # Preserve the actual labels/options in memory for the fill
                # plan but never emit them into the persistent trace.
                "required": field.required,
                "field_type": field.field_type,
                "option_count": len(field.options),
            }
            for field in fields
        ],
    )
    try:
        body_text = page.locator("body").inner_text(timeout=3000)
    except Exception:
        body_text = ""

    captcha = False
    try:
        captcha = page.locator("iframe[src*='recaptcha'], [data-sitekey], .g-recaptcha").count() > 0
    except Exception:
        pass

    captcha_fields = tuple(
        field
        for field in fields
        if "captcha" in f"{field.key} {field.label}".lower()
    )
    if captcha_fields:
        captcha = True

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
                options=f.options,
            )
            for f in fields
            if f not in captcha_fields
        ),
        profile,
        resume_path=resume_path,
        captcha_present=form_inspection.captcha_present,
        manual_auth_required=form_inspection.manual_auth_required,
        duplicate=duplicate,
        live_submission_enabled=live_submission_enabled,
    )



# Returned failures are zero-based field positions only; never emit the
# applicant's answers, input values, labels, or resume contents into logs.
_FORM_READBACK_PROBE = r"""(rows) => {
  const visible = el => {
    if (!el || !el.isConnected) return false;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 &&
      style.display !== 'none' && style.visibility !== 'hidden';
  };
  const clean = v => String(v == null ? '' : v).replace(/\s+/g, ' ').trim();
  const same = (a, b) => clean(a) === clean(b);
  const active = Array.from(document.querySelectorAll(
    '.jobs-easy-apply-modal, .artdeco-modal, [role="dialog"]'
  )).find(visible);
  const root = active || document;
  const inputs = Array.from(root.querySelectorAll('input, textarea, select'))
    .filter(el => !el.disabled && !el.readOnly &&
      (el.type || '').toLowerCase() !== 'hidden');

  const labelText = el => {
    let text = '';
    if (el.id) {
      const lbl = root.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (lbl) text += ' ' + (lbl.innerText || lbl.textContent || '');
    }
    if (!text) {
      const parent = el.closest('label');
      if (parent) text += ' ' + (parent.innerText || parent.textContent || '');
    }
    return clean(text);
  };

  const failures = [];
  for (let index = 0; index < rows.length; index++) {
    const row = rows[index];
    const matched = inputs.filter(el => el.name === row.key || el.id === row.key);
    if (!matched.length) { failures.push(index); continue; }
    const field = matched[0];
    const type = (field.type || '').toLowerCase();
    const expected = clean(row.expected);
    let valid = false;

    if (type === 'radio') {
      const checked = matched.filter(el => el.checked);
      valid = checked.length === 1 &&
        (same(checked[0].value, expected) ||
         same(labelText(checked[0]).replace(/\s*\(required\)\s*$/i, ''), expected));
    } else if (type === 'checkbox') {
      const shouldCheck = ['true', 'yes', '1', 'on', 'checked']
        .includes(expected.toLowerCase());
      valid = matched.length === 1 && field.checked === shouldCheck;
    } else if (field.tagName.toLowerCase() === 'select') {
      const selected = field.options && field.options[field.selectedIndex];
      valid = matched.length === 1 && !!selected &&
        (same(selected.value, expected) ||
         same(selected.label || selected.textContent, expected));
    } else {
      valid = matched.length === 1 && same(field.value, expected);
    }
    if (!valid) failures.push(index);
  }
  return failures;
}"""


def verify_filled_form_values(page, values: dict[str, str]) -> tuple[str, ...]:
    """Verify post-fill DOM state; only field indices leave browser memory.

    A click/fill API returning successfully is not proof that a reactive
    application retained the requested answer.
    """
    if not values:
        return ()
    rows = [{"key": key, "expected": str(value)} for key, value in values.items()]
    for attempt in range(3):
        try:
            failures = page.evaluate(_FORM_READBACK_PROBE, rows)
        except Exception:
            return ("form_readback_unavailable",)
        if not isinstance(failures, list) or any(
            isinstance(value, bool) or not isinstance(value, int)
            or value < 0 or value >= len(rows)
            for value in failures
        ):
            return ("form_readback_invalid",)
        if not failures:
            return ()
        if attempt < 2:
            try:
                page.wait_for_timeout(200)
            except Exception:
                break
    # Never log keys/answers; a position corresponds only to a plan's order.
    return tuple(
        f"field_value_unverified:{index}"
        for index in sorted(set(failures))
    )


def apply_fill_plan(page, plan: FillPlan, *, verify_readback: bool = False) -> tuple[str, ...]:
    fill_failures: list[str] = []

    if not plan.can_fill:
        return tuple(dict.fromkeys([*plan.reasons, *fill_failures]))

    for key, value in plan.values.items():
        modal_selector = (
            f'.jobs-easy-apply-modal [name="{key}"], '
            f'.jobs-easy-apply-modal [id="{key}"], '
            f'[role="dialog"] [name="{key}"], '
            f'[role="dialog"] [id="{key}"]'
        )
        fallback_selector = f'[name="{key}"], [id="{key}"]'
        try:
            try:
                target = page.locator(modal_selector).first
                if not target.count():
                    target = page.locator(fallback_selector).first
            except Exception:
                target = page.locator(fallback_selector).first
            if not target.count():
                fill_failures.append(f"field_not_found:{key}")
                continue

            tag = target.evaluate("(el) => el.tagName.toLowerCase()")
            input_type = (target.get_attribute("type") or "").lower()

            if tag == "select":
                try:
                    target.select_option(label=value)
                except Exception:
                    wanted = value.strip().lower()
                    options = target.evaluate(
                        """(el) => Array.from(el.options).map((o) => ({
                          label: (o.textContent || '').replace(/\\s+/g, ' ').trim(),
                          value: o.value || ''
                        }))"""
                    ) or []
                    matched = None
                    for option in options:
                        label = str(option.get("label", "")).strip()
                        raw_value = str(option.get("value", "")).strip()
                        if wanted in {label.lower(), raw_value.lower()} or (
                            wanted and wanted in label.lower()
                        ):
                            matched = (label, raw_value)
                            break
                    if not matched:
                        raise
                    label, raw_value = matched
                    if label:
                        target.select_option(label=label)
                    else:
                        target.select_option(value=raw_value)

            elif input_type == "checkbox":
                wanted = value.strip().lower()
                should_check = wanted in {"true", "yes", "1", "on", "checked"}
                if should_check:
                    target.check(timeout=2000)
                    if not target.is_checked():
                        fill_failures.append(f"checkbox_not_selected:{key}")
                elif target.is_checked():
                    target.uncheck(timeout=2000)

            elif input_type == "radio":
                try:
                    options = page.locator(
                        f'.jobs-easy-apply-modal input[type="radio"][name="{key}"], '
                        f'[role="dialog"] input[type="radio"][name="{key}"]'
                    )
                    if not options.count():
                        options = page.locator(f'input[type="radio"][name="{key}"]')
                except Exception:
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

                    if not option_label:
                        try:
                            option_label = option.evaluate(
                                "(el) => ((el.parentElement && el.parentElement.innerText) || '').trim().toLowerCase()"
                            )
                        except Exception:
                            option_label = ""

                    if wanted not in {option_value, option_label}:
                        continue

                    matched = True
                    checked = False

                    try:
                        option.check(timeout=2000)
                        checked = option.is_checked()
                    except Exception:
                        checked = False

                    if not checked and option_id:
                        try:
                            label = page.locator(f'label[for="{option_id}"]').first
                            if label.count():
                                label.click(timeout=2000)
                                checked = option.is_checked()
                        except Exception:
                            checked = False

                    if not checked:
                        try:
                            option.click(timeout=2000)
                            checked = option.is_checked()
                        except Exception:
                            checked = False

                    if not checked:
                        fill_failures.append(f"radio_not_selected:{key}")
                    break

                if not matched:
                    fill_failures.append(f"radio_option_not_found:{key}")

            else:
                target.fill(value)

        except Exception as exc:
            fill_failures.append(f"field_fill_failed:{key}:{type(exc).__name__}")

    if plan.resume_path:
        try:
            upload = page.locator('input[type="file"]').first
            if not upload.count():
                return tuple(dict.fromkeys([*plan.reasons, "resume_upload_input_not_found"]))
            upload.set_input_files(plan.resume_path)
        except Exception:
            return tuple(dict.fromkeys([*plan.reasons, "resume_upload_failed"]))

    if verify_readback and not fill_failures and plan.values:
        fill_failures.extend(verify_filled_form_values(page, plan.values))
    return tuple(dict.fromkeys([*plan.reasons, *fill_failures]))
