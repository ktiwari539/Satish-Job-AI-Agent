"""Read-only, exact-ID LinkedIn job application status check.

Does not open Easy Apply, click Submit, or write an application ledger.
Absence of a visible Applied indicator never proves an application failed.
"""
from urllib.parse import urlsplit
from linkedin_exact_job import ensure_exact_target


# Only on the exact LinkedIn /jobs/view/ID route. No user-supplied selectors.
_APPLIED_PROBE = r"""() => {
  const visible = el => {
    if (!el || !el.isConnected) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 &&
      s.display !== 'none' && s.visibility !== 'hidden';
  };
  const normalize = el => String(
    el.getAttribute('aria-label') || el.innerText ||
    el.textContent || el.getAttribute('value') || ''
  ).replace(/\s+/g, ' ').trim().toLowerCase();
  const controls = Array.from(document.querySelectorAll(
    'button, [role="button"], .jobs-apply-button, ' +
    '.jobs-apply-button--applied, [data-control-name*="applied"]'
  )).filter(visible);
  if (controls.some(el =>
      /^(applied|application submitted|application sent)$/i.test(normalize(el)))) {
    return { applied: true, evidence: 'exact_job_applied_control' };
  }
  // This link's exact job ID is checked again in Python, so a specific
  // applied label on the job panel can be used as additional evidence.
  const panels = Array.from(document.querySelectorAll(
    '.jobs-unified-top-card, .job-details-jobs-unified-top-card, ' +
    '.jobs-details-top-card, .job-details-module, .job-view-layout'
  )).filter(visible);
  if (panels.some(panel =>
      Array.from(panel.querySelectorAll('span, div, p'))
        .filter(visible)
        .some(el => /^applied(?:\s+on\s+.+)?$/i.test(normalize(el))))) {
    return { applied: true, evidence: 'exact_job_applied_badge' };
  }
  // LinkedIn also renders a read-only "Application status" section with
  // "Application submitted" instead of an Applied button. Check only a
  // compact, visible section containing both labels; never search body text.
  const statusLabels = Array.from(document.querySelectorAll(
    'h2, h3, h4, h5, [role="heading"], dt, strong, span, p, div'
  )).filter(visible).filter(el => normalize(el) === 'application status');
  for (const label of statusLabels) {
    let section = label.parentElement;
    for (let depth = 0; depth < 4 && section; depth++, section = section.parentElement) {
      if (!visible(section)) break;
      const sectionText = String(section.innerText || section.textContent || '')
        .replace(/\\s+/g, ' ').trim();
      // Prevent unrelated job cards or historic status text elsewhere on the page.
      if (sectionText.length > 320) break;
      const statusNodes = Array.from(section.querySelectorAll(
        'h2, h3, h4, h5, span, p, div, strong, dd'
      )).filter(visible);
      if (statusNodes.some(node =>
          node !== label && /^(application submitted|application sent)$/i.test(normalize(node)))) {
        return { applied: true, evidence: 'exact_job_application_status' };
      }
    }
  }
  return { applied: false, evidence: '' };
}"""


def inspect_exact_applied_status(page, target):
    """Return positive on-page evidence or unverified; never 'not applied'."""
    ensure_exact_target(page, target)
    before = str(page.url)
    try:
        raw = page.evaluate(_APPLIED_PROBE)
    except Exception:
        raw = None
    ensure_exact_target(page, target)
    if str(page.url) != before:
        return {"status": "application_status_unverified", "reason": "page_changed"}
    allowed = {"exact_job_applied_control", "exact_job_applied_badge",
               "exact_job_application_status"}
    if (isinstance(raw, dict) and raw.get("applied") is True
            and raw.get("evidence") in allowed):
        return {
            "status": "linkedin_exact_job_applied_visible",
            "evidence_kind": raw["evidence"],
        }
    return {
        "status": "application_status_unverified",
        "reason": "no_positive_applied_indicator_in_exact_job_dom",
    }
