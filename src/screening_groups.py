"""Verified LinkedIn screening group extraction and answer selection.

This is a dedicated bridge for styled native/ARIA radio controls. It uses
a strictly scoped active Easy Apply surface, returns the employer's prompt
instead of Yes/No option labels, and verifies actual selection in the DOM.
Question and answer content remain in memory only; log counts, never text.
"""
from dataclasses import dataclass
from typing import Mapping

from question_resolver import (
    match_answer_to_option, normalize_question, resolve_application_answer,
)


# The functions are intentionally part of one JavaScript expression: click and
# scan build identical group IDs on the CURRENT rendered application screen.
_GROUPS_JS = r"""async (command) => {
  const norm = value => String(value || '').toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ').trim().replace(/\s+/g, ' ');
  const clean = value => String(value || '').replace(/\s+/g, ' ').trim();
  const visible = el => {
    if (!el || !el.isConnected) return false;
    const box = el.getBoundingClientRect(), style = getComputedStyle(el);
    return box.width > 0 && box.height > 0 && style.display !== 'none' &&
      style.visibility !== 'hidden';
  };
  const usable = el => {
    if (el.disabled || el.getAttribute('aria-disabled') === 'true')
      return false;
    return visible(el) || Array.from(el.labels || []).some(visible) ||
      !!(el.closest('label') && visible(el.closest('label')));
  };
  // Do not read arbitrary search results or unrelated job cards. A verified
  // Easy Apply caller may have a role-less inline wizard with this wrapper.
  const dialogs = Array.from(document.querySelectorAll(
    '.jobs-easy-apply-modal, .artdeco-modal, [role="dialog"]'
  )).filter(visible);
  const inline = Array.from(document.querySelectorAll(
    '.jobs-easy-apply-content, .jobs-easy-apply-form, ' +
    '[data-test*="easy-apply-form"], .jobs-easy-apply-form-section'
  )).filter(visible);
  const root = dialogs[0] || inline[0];
  if (!root) return command.action === 'scan' ? [] : {status:'no_wizard'};
  const optionLabel = el => {
    const labels = Array.from(el.labels || []);
    const explicit = el.id && document.querySelector(
      'label[for="' + CSS.escape(el.id) + '"]'
    );
    if (explicit) labels.push(explicit);
    const wrapping = el.closest('label');
    if (wrapping) labels.push(wrapping);
    // Prefer visible, individual option labels over the whole parent group.
    const candidates = [
      ...labels.map(x => clean(x.innerText || x.textContent)),
      clean(el.getAttribute('aria-label')),
      el.matches('[role="radio"]') ? clean(el.innerText || el.textContent) : '',
      clean(el.getAttribute('value'))
    ];
    return candidates.find(value =>
      value && value.length <= 120 &&
      !/^(on|off|null|undefined)$/i.test(value)) || '';
  };
  const selected = el => el.checked === true ||
    el.getAttribute('aria-checked') === 'true';
  const groupSelector = [
    '[role="radiogroup"]', 'fieldset',
    '[data-test-form-builder-radio-button-form-component]',
    '[class*="radio-button-form-component"]',
    '.fb-dash-form-element',
    '.jobs-easy-apply-form-section__grouping',
  ].join(',');
  const controls = Array.from(root.querySelectorAll(
    'input[type="radio"], [role="radio"]'
  )).filter(usable);
  const grouped = new Map();
  for (const control of controls) {
    const name = clean(control.getAttribute('name'));
    const group = control.closest(groupSelector);
    // Native name is a stronger boundary than a shared React wrapper.
    // If neither name nor a real question-group wrapper exists, do not
    // guess that unrelated radio buttons belong to the same question.
    const key = name ? 'name:' + name : group;
    if (!key) continue;
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(control);
  }
  const questionText = (group, members) => {
    const scope = group || members[0].closest(groupSelector);
    if (!scope || !root.contains(scope)) return '';
    const labelledBy = clean(scope.getAttribute('aria-labelledby'));
    if (labelledBy) {
      const parts = labelledBy.split(/\s+/).map(id =>
        clean(document.getElementById(id)?.textContent)).filter(Boolean);
      if (parts.length) return clean(parts.join(' '));
    }
    const selectors = [
      'legend', '[data-test*="question"]',
      '.fb-dash-form-element__label', '[class*="form-element__label"]',
      '[class*="question-label"]'
    ];
    for (const selector of selectors) {
      const node = scope.querySelector(selector);
      const value = clean(node?.innerText || node?.textContent);
      if (value.length >= 6 && value.length < 450 &&
          !/^(yes|no|true|false)$/i.test(value)) return value;
    }
    return '';
  };
  const groups = [];
  for (const [key, members] of grouped) {
    const wrapper = typeof key === 'string' ?
      members[0].closest(groupSelector) : key;
    const question = questionText(wrapper, members);
    if (!question) continue;
    // Multiple React wrappers may represent the same option. Deduplicate
    // labels for the question, but do not infer an answer from them.
    const optionMap = new Map();
    for (const el of members) {
      const label = optionLabel(el);
      if (!label) continue;
      const normalized = norm(label);
      if (!optionMap.has(normalized)) optionMap.set(normalized, []);
      optionMap.get(normalized).push(el);
    }
    const options = [...optionMap.keys()];
    if (!options.length || options.length > 30) continue;
    const required = wrapper?.getAttribute('aria-required') === 'true' ||
      wrapper?.getAttribute('data-required') === 'true' ||
      members.some(el => el.required || el.getAttribute('aria-required') === 'true') ||
      /\*\s*$|\(required\)/i.test(question) ||
      !!wrapper?.querySelector(
        '[class*="required-indicator"],[class*="required-marker"]');
    groups.push({
      question, options: options.map(name =>
        optionLabel(optionMap.get(name)[0])),
      required: !!required, selected: members.some(selected),
      members, optionMap
    });
  }
  if (command.action === 'scan') return groups.slice(0, 40).map((g,index) => ({
    index, question:g.question, options:g.options,
    required:g.required, selected:g.selected
  }));
  if (command.action !== 'select') return {status:'invalid_action'};
  const group = groups[command.index];
  if (!group || norm(group.question) !== norm(command.question))
    return {status:'stale_group'};
  const wanted = norm(command.answer);
  const matches = group.optionMap.get(wanted) || [];
  if (!matches.length) return {status:'no_option'};
  const visibleChoices = matches.filter(visible);
  const choices = visibleChoices.length === 1 ? visibleChoices : matches;
  if (choices.length !== 1) return {status:'ambiguous'};
  const control = choices[0];
  if (!selected(control)) {
    try {
      if (visible(control)) control.click();
      else {
        const label = Array.from(control.labels || []).find(visible) ||
          control.closest('label');
        if (!label || !visible(label)) return {status:'not_clickable'};
        label.click();
      }
      await new Promise(resolve => requestAnimationFrame(resolve));
    } catch (_) {
      return {status:'click_failed'};
    }
  }
  const confirmed = matches.some(selected);
  return {status:confirmed ? 'confirmed' : 'unverified'};
}"""


@dataclass(frozen=True)
class ScreeningResult:
    groups_found: int = 0
    choices_confirmed: int = 0
    unresolved_questions: tuple[str, ...] = ()
    verification_failures: int = 0
    answered_questions: tuple[str, ...] = ()


def inspect_screening_groups(page) -> tuple[dict, ...]:
    """Extract in-memory question/option groups, never emitting them to logs."""
    try:
        raw = page.evaluate(_GROUPS_JS, {"action": "scan"})
    except Exception:
        return ()
    if not isinstance(raw, list):
        return ()
    groups = []
    for item in raw[:40]:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question", "")).strip()
        options = item.get("options", [])
        index = item.get("index")
        if not (6 <= len(question) <= 450 and
                type(index) is int and index >= 0 and
                isinstance(options, list) and 1 <= len(options) <= 30):
            continue
        cleaned_options = tuple(str(x).strip() for x in options
                                if isinstance(x, str) and 0 < len(x.strip()) <= 120)
        if cleaned_options:
            groups.append({
                "index": index, "question": question,
                "options": cleaned_options,
                "required": item.get("required") is True,
                "selected": item.get("selected") is True,
            })
    return tuple(groups)


def answer_verified_screening_groups(page, profile: Mapping[str, object]) -> ScreeningResult:
    """Never guess; block or ask only for actual unanswered employer prompts."""
    groups = inspect_screening_groups(page)
    unresolved = []
    answered = []
    confirmed = 0
    failed = 0
    for group in groups:
        if group["selected"]:
            confirmed += 1
            answered.append(normalize_question(group["question"]))
            continue
        resolved = resolve_application_answer(
            group["question"], profile, options=group["options"],
            required=True,
        )
        if resolved.status != "RESOLVED":
            unresolved.append(group["question"])
            continue
        choice = match_answer_to_option(resolved.answer, group["options"])
        if not choice:
            unresolved.append(group["question"])
            continue
        try:
            result = page.evaluate(_GROUPS_JS, {
                "action": "select", "index": group["index"],
                "question": group["question"], "answer": choice,
            })
        except Exception:
            result = {}
        if isinstance(result, dict) and result.get("status") == "confirmed":
            confirmed += 1
            answered.append(normalize_question(group["question"]))
        else:
            failed += 1
            unresolved.append(group["question"])
    return ScreeningResult(
        groups_found=len(groups), choices_confirmed=confirmed,
        unresolved_questions=tuple(dict.fromkeys(unresolved)),
        verification_failures=failed,
        answered_questions=tuple(answered),
    )
