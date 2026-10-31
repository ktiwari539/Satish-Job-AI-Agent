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
  const panels = Array.from(document.querySelectorAll(
    '.jobs-unified-top-card, .job-details-jobs-unified-top-card, ' +
    '.jobs-details-top-card, .job-details-module, .job-view-layout'
  )).filter(visible);
  const main = document.querySelector('main');
  const root = panels.length === 1 ? panels[0] :
    main && Array.from(main.querySelectorAll('h1')).filter(visible).length === 1 ? main : null;
  const routeId = location.pathname.match(/\/jobs\/view\/(?:[^/?]+-)?(\d{7,15})\/?$/)?.[1];
  const controls = root ? Array.from(root.querySelectorAll(
    'button, [role="button"], .jobs-apply-button, ' +
    '.jobs-apply-button--applied, [data-control-name*="applied"]'
  )).filter(visible).filter(el => {
    if (el.closest('aside')) return false;
    const card = el.closest('[data-job-id],[data-occludable-job-id]');
    return !card || [card.getAttribute('data-job-id'),card.getAttribute('data-occludable-job-id')].includes(routeId);
  }) : [];
  if (controls.some(el =>
      /^(applied|application submitted|application sent)$/i.test(normalize(el)))) {
    return { applied: true, evidence: 'exact_job_applied_control' };
  }
  // This link's exact job ID is checked again in Python, so a specific
  // applied label on the job panel can be used as additional evidence.
  if (panels.some(panel =>
      Array.from(panel.querySelectorAll('span, div, p'))
        .filter(visible)
        .some(el => /^applied(?:\s+on\s+.+)?$/i.test(normalize(el))))) {
    return { applied: true, evidence: 'exact_job_applied_badge' };
  }
  // LinkedIn also renders a read-only "Application status" section with
  // "Application submitted" instead of an Applied button. Check only a
  // compact, visible section containing both labels; never search body text.
  const exactJobPanels = Array.from(document.querySelectorAll(
    '.jobs-unified-top-card, .job-details-jobs-unified-top-card, ' +
    '.jobs-details-top-card, .job-details-module'
  )).filter(visible);
  // Some LinkedIn /jobs/view/ID pages render the job title and
  // "Application status" as SIBLING cards in a left job-content column.
  // Such a card is not contained inside .jobs-details-top-card, so the
  // previous selector reported ambiguous even though the applicant had
  // already submitted. Require unusually strong, independent evidence:
  // a visible unique job title on the left, the submitted status, a
  // "View resume" link IN the compact status card and aligned columns.
  // The Python caller separately pins and rechecks the exact job ID.
  const jobHeadings = Array.from(document.querySelectorAll('h1'))
    .filter(visible)
    .filter(el => normalize(el).length >= 8 &&
      !/^(jobs|linkedin|job details|job search)$/.test(normalize(el)));
  const sameJobColumn = label => {
    if (jobHeadings.length !== 1) return false;
    const title = jobHeadings[0];
    const titleBox = title.getBoundingClientRect();
    const statusBox = label.getBoundingClientRect();
    if (Math.abs(titleBox.left - statusBox.left) > 80 ||
        statusBox.top <= titleBox.top) return false;
    const titleMain = title.closest('main, [role="main"], .scaffold-layout__main');
    const statusMain = label.closest('main, [role="main"], .scaffold-layout__main');
    // If the DOM provides a main landmark, both elements must share it.
    if (titleMain || statusMain) {
      if (!titleMain || titleMain !== statusMain) return false;
    }
    return true;
  };
  const statusLabels = Array.from(document.querySelectorAll(
    'h2, h3, h4, h5, [role="heading"], dt, strong, span, p, div'
  )).filter(visible).filter(el => normalize(el) === 'application status');
  let unscopedSubmittedStatus = false;
  for (const label of statusLabels) {
    let section = label.parentElement;
    for (let depth = 0; depth < 4 && section; depth++, section = section.parentElement) {
      if (!visible(section)) break;
      const sectionText = String(section.innerText || section.textContent || '')
        .replace(/\s+/g, ' ').trim();
      if (sectionText.length > 320) break;
      const statusNodes = Array.from(section.querySelectorAll(
        'h2, h3, h4, h5, span, p, div, strong, dd'
      )).filter(visible);
      const submitted = statusNodes.some(node =>
        node !== label &&
        /^(application submitted|application sent)$/i.test(normalize(node)));
      if (!submitted) continue;
      // The exact /jobs/view/ID route alone does not prove a globally
      // discovered application-status widget belongs to this job. Avoid
      // treating a side panel or unrelated card as positive evidence.
      if (exactJobPanels.some(panel =>
          panel.contains(label) && panel.contains(section))) {
        return { applied: true, evidence: 'exact_job_application_status' };
      }
      // Strong sibling-card evidence: "View resume" is in the SAME
      // compact status card, not a Premium sidebar or another job tile.
      const resumeLink = Array.from(section.querySelectorAll(
        'a, button, [role="link"]'
      )).filter(visible).some(node =>
        /^view resume$/i.test(normalize(node)));
      if (resumeLink && sameJobColumn(label)) {
        return {
          applied: true, evidence: 'exact_job_sibling_application_status'
        };
      }
      unscopedSubmittedStatus = true;
      break;
    }
  }
  return {
    applied: false, evidence: '',
    ambiguous_unscoped_status: unscopedSubmittedStatus
  };
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
    if isinstance(raw, dict) and raw.get("ambiguous_unscoped_status") is True:
        return {
            "status": "application_status_ambiguous",
            "reason": "submitted_status_not_scoped_to_current_job_panel",
        }
    allowed = {"exact_job_applied_control", "exact_job_applied_badge",
               "exact_job_application_status",
               "exact_job_sibling_application_status"}
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
