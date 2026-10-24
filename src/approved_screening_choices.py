"""Apply only explicitly saved, exact employer question answers.

The private profile's \`answers\` map supplies truth. This module never
generates an answer, clicks Next/Review/Submit, or persists answer content in
traces. It is usable only after the caller verified an Easy Apply form opened.
"""
from collections.abc import Mapping

from question_resolver import normalize_question


_CHOICE_SCRIPT = r"""async (approved) => {
  const norm = s => String(s || '').toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ').trim().replace(/\s+/g, ' ');
  const visible = el => {
    if (!el || !el.isConnected) return false;
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 &&
      s.display !== 'none' && s.visibility !== 'hidden';
  };
  const usable = el => {
    if (el.disabled || el.getAttribute('aria-disabled') === 'true')
      return false;
    return visible(el) || Array.from(el.labels || []).some(visible) ||
      Boolean(el.closest('label') && visible(el.closest('label')));
  };
  const controls = root => Array.from(root.querySelectorAll(
    'input[type="radio"], [role="radio"]'
  )).filter(usable);
  const optionText = el => {
    const candidates = [
      el.getAttribute('aria-label'), el.getAttribute('value'),
      ...(Array.from(el.labels || []).map(x => x.innerText || x.textContent)),
      el.matches('[role="radio"]') ? el.innerText || el.textContent : '',
      el.closest('label')?.innerText,
    ];
    // Names of employer questions must never be interpreted as option text.
    return candidates.map(norm).find(v =>
      ['yes','no','true','false'].includes(v)) || '';
  };
  const groupRoots = Array.from(document.querySelectorAll(
    'fieldset, [role="radiogroup"], ' +
    '.fb-dash-form-element, [class*="form-element"], ' +
    '[data-test-form-builder-radio-button-form-component], ' +
    '[class*="radio-button-form-component"], ' +
    '.jobs-easy-apply-form-section__grouping'
  )).filter(visible);
  const stats = {present:0, confirmed:0, ambiguous:0,
    unverified:0, missing_controls:0};
  for (const pair of approved) {
    // Only exact question text, allowing trailing Yes/No labels; do not
    // match an unrelated substring buried in general page text.
    const roots = groupRoots.filter(root => {
      const t = norm(root.innerText || root.textContent);
      return (t === pair.question || t.startsWith(pair.question + ' ')) &&
        controls(root).length >= 1;
    }).sort((a,b) => (a.innerText || '').length - (b.innerText || '').length);
    if (!roots.length) continue;
    stats.present++;
    const root = roots[0];
    const candidates = controls(root)
      .filter(el => optionText(el) === pair.answer);
    const visibleCandidates = candidates.filter(visible);
    // Native input and role=radio wrapper can represent the same option.
    const preferred = visibleCandidates.length === 1
      ? visibleCandidates : candidates;
    if (preferred.length !== 1) {
      if (!candidates.length) stats.missing_controls++;
      else stats.ambiguous++;
      continue;
    }
    const choice = preferred[0];
    const selected = el => Boolean(el.checked) ||
      el.getAttribute('aria-checked') === 'true';
    if (!selected(choice)) {
      choice.click();
      await new Promise(resolve => requestAnimationFrame(() => resolve()));
    }
    if (selected(choice) ||
        controls(root).some(el => optionText(el) === pair.answer && selected(el)))
      stats.confirmed++;
    else stats.unverified++;
  }
  return stats;
}"""


def apply_approved_yes_no_answers(page, profile):
    """Return only numeric proof; absence of answers is a read-only no-op."""
    raw = profile.get("answers", {})
    if not isinstance(raw, Mapping):
        return {"present": 0, "confirmed": 0, "ambiguous": 0,
                "unverified": 0, "missing_controls": 0}
    approved = []
    for question, answer in raw.items():
        normalized = normalize_question(question)
        normalized_answer = normalize_question(answer)
        if len(normalized) < 18 or normalized_answer not in ("yes", "no"):
            continue
        approved.append({"question": normalized, "answer": normalized_answer})
        if len(approved) >= 100:
            break
    if not approved:
        return {"present": 0, "confirmed": 0, "ambiguous": 0,
                "unverified": 0, "missing_controls": 0}
    try:
        result = page.evaluate(_CHOICE_SCRIPT, approved)
    except Exception:
        return {"present": 0, "confirmed": 0, "ambiguous": 0,
                "unverified": 1, "missing_controls": 0}
    expected = ("present", "confirmed", "ambiguous",
                "unverified", "missing_controls")
    if not isinstance(result, dict):
        return {"present": 0, "confirmed": 0, "ambiguous": 0,
                "unverified": 1, "missing_controls": 0}
    return {key: max(0, min(100, result.get(key, 0)))
            if type(result.get(key)) is int else 0
            for key in expected}
