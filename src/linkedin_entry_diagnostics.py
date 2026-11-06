"""Read-only exact-job entry classification. Only enums/counts leave the DOM."""
from urllib.parse import urlsplit

from linkedin_exact_job import parse_linkedin_target


_ENTRY_PROBE = r"""() => {
  const visible = el => {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
  };
  const text = el => String(el?.innerText || el?.textContent || '').replace(/\s+/g, ' ').trim();
  const panels = [...document.querySelectorAll(
    '.job-details-jobs-unified-top-card,.jobs-unified-top-card,.jobs-details-top-card'
  )].filter(visible);
  const main = document.querySelector('main');
  const root = panels.length === 1 ? panels[0] :
    main && [...main.querySelectorAll('h1')].filter(visible).length === 1 ? main : null;
  const controls = root ? [...root.querySelectorAll('a,button,[role="button"]')].filter(visible) : [];
  const identity = el => (text(el) || el.getAttribute('aria-label') || '').toLowerCase();
  const isExternal = el => {
    if (/apply on company|apply on.*website/i.test(identity(el))) return true;
    if (!/^apply(?: now)?$/i.test(identity(el))) return false;
    const href = el.getAttribute('href');
    if (!href) return true; // A plain Apply button never proves Easy Apply.
    try { const u = new URL(href, location.href);
      return !['linkedin.com','www.linkedin.com'].includes(u.hostname) || u.pathname.startsWith('/safety/go/');
    } catch { return false; }
  };
  const body = text(document.body).toLowerCase();
  return {
    scoped: !!root,
    easy_controls: controls.filter(el => /^easy apply\b|^continue applying\b/i.test(identity(el))).length,
    external_controls: controls.filter(isExternal).length,
    applied_controls: controls.filter(el => /^(applied|application submitted|application sent)$/i.test(identity(el))).length,
    unavailable: !!root && /no longer accepting applications|job (?:is no longer available|has expired)|no longer available/i.test(text(root)),
    sign_in: !!document.querySelector('input[type="password"],form[action*="login"]'),
    challenge: /verify your identity|security checkpoint|verify you are human/.test(body),
    loading: [...document.querySelectorAll('[role="progressbar"],.artdeco-loader')].filter(visible).length,
    heading_count: [...document.querySelectorAll('h1')].filter(visible).length,
  };
}"""


def classify_linkedin_entry(page, job_url, *, entry=None, applied_status=""):
    """Classify the current exact job without clicking or exporting page text."""
    signals = {}
    try:
        target = parse_linkedin_target(job_url)
        route = parse_linkedin_target(str(page.url))
        route_ok = target.job_id == route.job_id
    except (ValueError, TypeError, AttributeError):
        route_ok = False
    try:
        raw = page.evaluate(_ENTRY_PROBE)
    except Exception:
        raw = None
    if isinstance(raw, dict):
        for key in ("scoped", "unavailable", "sign_in", "challenge"):
            signals[key] = raw.get(key) is True
        for key in ("easy_controls", "external_controls", "applied_controls", "loading", "heading_count"):
            val = raw.get(key)
            signals[key] = max(0, min(200, val)) if type(val) is int else 0
    path = urlsplit(str(getattr(page, "url", ""))).path
    if signals.get("challenge") or path.startswith('/checkpoint'):
        classification = "AUTH_REQUIRED"
    elif signals.get("sign_in") or path.startswith(('/login', '/signup', '/authwall')):
        classification = "AUTH_REQUIRED"
    elif not route_ok:
        classification = "PAGE_MISMATCH"
    elif applied_status == "applied" or signals.get("applied_controls"):
        classification = "ALREADY_APPLIED"
    elif applied_status == "ambiguous":
        classification = "APPLIED_STATUS_AMBIGUOUS"
    elif signals.get("unavailable"):
        classification = "UNAVAILABLE"
    elif (getattr(entry, "application_type", "") == "LINKEDIN_EASY_APPLY"
          and getattr(entry, "application_state", "") in ("APPLICATION_ENTRY_FOUND", "FORM_READY")):
        classification = "EASY_APPLY"
    elif (getattr(entry, "application_type", "") == "EXTERNAL_APPLY"
          or signals.get("external_controls")):
        classification = "EXTERNAL_APPLY"
    elif signals.get("easy_controls"):
        classification = "SELECTOR_LAYOUT_FAILURE"
    elif signals.get("loading"):
        classification = "PAGE_NOT_READY"
    elif signals.get("scoped"):
        classification = "SELECTOR_LAYOUT_FAILURE"
    else:
        classification = "UNRECOGNIZED_LAYOUT"
    return {"entry_classification": classification, "entry_signals": signals}
