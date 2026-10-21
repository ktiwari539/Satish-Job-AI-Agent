"""Read-only and privacy-limited DOM diagnosis for one LinkedIn job page.

Never captures full HTML, text, selectors with user content, cookies, tokens,
URLs, screenshots, or network traffic. Never clicks, applies, or submits.
"""
from urllib.parse import urlsplit

from agent_trace import trace_event
from linkedin_exact_job import LinkedInTarget
from linkedin_selected_search import _selected_route_verified, _selected_search_url
from navigation import bounded_goto


# Evaluated on the local Playwright page; only bounded counts and booleans
# leave the browser. A target job ID is passed as a separate argument.
_READ_ONLY_PROBE = r"""(targetId) => {
  const count = (selector) => {
    try { return Math.min(10000, document.querySelectorAll(selector).length); }
    catch { return 0; }
  };
  const yes = (selector) => count(selector) > 0;
  const body = document.body;
  const text = String(body?.innerText || '').toLowerCase();
  const bounded = (n) => Math.min(Math.max(0, n), 100000);
  const navRoute = String(location.pathname || '');
  const hrefs = document.querySelectorAll('a[href]');
  let jobLinks = 0, targetLinks = 0;
  for (const anchor of hrefs) {
    let pathname = '';
    try {
      const url = new URL(anchor.getAttribute('href'), location.href);
      if (!['linkedin.com', 'www.linkedin.com'].includes(url.hostname)) continue;
      pathname = url.pathname;
    } catch { continue; }
    const m = pathname.match(/\/jobs\/view\/(?:[^/?]*-)?(\d{7,15})(?:\/|$)/);
    if (!m) continue;
    jobLinks += 1;
    if (m[1] === targetId) targetLinks += 1;
  }
  let idNodes = 0, targetIdNodes = 0;
  for (const node of document.querySelectorAll('[data-job-id],[data-occludable-job-id]')) {
    idNodes += 1;
    if ([node.getAttribute('data-job-id'),
         node.getAttribute('data-occludable-job-id')].includes(targetId)) targetIdNodes += 1;
  }
  return {
    body_chars: bounded(text.length),
    ready_complete: document.readyState === 'complete',
    route_search: ['/jobs/search', '/jobs/search/', '/jobs/search-results', '/jobs/search-results/'].includes(navRoute),
    main_count: count('main'),
    heading_count: count('h1'),
    iframe_count: count('iframe'),
    all_list_items: count('li'),
    aria_list_items: count('[role="listitem"]'),
    scaffold_cards: count('li.scaffold-layout__list-item'),
    results_cards: count('li.jobs-search-results__list-item'),
    container_cards: count('div.job-card-container'),
    job_links: bounded(jobLinks),
    exact_job_links: bounded(targetLinks),
    job_id_nodes: bounded(idNodes),
    exact_job_id_nodes: bounded(targetIdNodes),
    detail_roots: count('.jobs-search__job-details--container, .jobs-search__job-details, .jobs-details, .scaffold-layout__detail'),
    job_description_nodes: count('.jobs-description, .jobs-description__content, .jobs-box__html-content'),
    loading_nodes: count('[role="progressbar"],.artdeco-loader,.loading-spinner'),
    password_input: yes('input[type="password"]'),
    challenge_hint: text.includes('verify your identity') || text.includes('security checkpoint') || text.includes('captcha'),
    no_jobs_hint: text.includes('no matching jobs') || text.includes('no results found') || text.includes('no jobs found'),
    sign_in_hint: text.includes('sign in to linkedin') || text.includes('join linkedin to see'),
    generic_error_hint: text.includes('something went wrong') || text.includes('unable to load jobs'),
  };
}"""


_FIELDS = (
    "body_chars", "ready_complete", "route_search", "main_count", "heading_count",
    "iframe_count", "all_list_items", "aria_list_items", "scaffold_cards",
    "results_cards", "container_cards", "job_links", "exact_job_links",
    "job_id_nodes", "exact_job_id_nodes", "detail_roots",
    "job_description_nodes", "loading_nodes", "password_input",
    "challenge_hint", "no_jobs_hint", "sign_in_hint", "generic_error_hint",
)
_BOOL_FIELDS = (
    "ready_complete", "route_search", "password_input", "challenge_hint",
    "no_jobs_hint", "sign_in_hint", "generic_error_hint",
)


def _validate_signals(raw):
    """Never reflect arbitrary page-provided strings or unexpected fields."""
    if not isinstance(raw, dict):
        return {"diagnosis": "probe_unavailable"}
    clean = {}
    for name in _FIELDS:
        val = raw.get(name)
        if name in _BOOL_FIELDS:
            clean[name] = val if type(val) is bool else False
        else:
            clean[name] = min(max(val, 0), 100000) if type(val) is int else 0
    if clean["challenge_hint"]:
        state = "challenge_detected"
    elif clean["password_input"] or clean["sign_in_hint"]:
        state = "sign_in_required"
    elif clean["no_jobs_hint"]:
        state = "no_jobs_displayed"
    elif clean["generic_error_hint"]:
        state = "linkedin_error_page"
    elif clean["exact_job_links"] or clean["exact_job_id_nodes"]:
        state = "exact_job_dom_present_selector_mismatch"
    elif clean["job_links"] or clean["job_id_nodes"]:
        state = "other_job_dom_present_target_missing"
    elif clean["loading_nodes"]:
        state = "jobs_still_loading"
    elif clean["body_chars"] > 100 and clean["route_search"]:
        state = "search_page_without_job_markup"
    else:
        state = "unrecognized_or_empty_page"
    clean["diagnosis"] = state
    return clean


def diagnose_linkedin_search_page(page, target: LinkedInTarget, *, source_url: str, keywords: str):
    """Visit the user's selected search route once; never clicks any control."""
    search_url = _selected_search_url(target, keywords, source_url)
    bounded_goto(page, search_url)
    if not _selected_route_verified(page, target):
        raise ValueError("diagnostic_target_route_changed")
    try:
        page.wait_for_timeout(1200)
    except Exception:
        pass
    if not _selected_route_verified(page, target):
        raise ValueError("diagnostic_target_route_changed")
    try:
        data = page.evaluate(_READ_ONLY_PROBE, target.job_id)
    except Exception:
        data = None
    diagnosis = _validate_signals(data)
    trace_event("linkedin_read_only_dom_diagnosis", job_id=target.job_id, **diagnosis)
    return diagnosis
