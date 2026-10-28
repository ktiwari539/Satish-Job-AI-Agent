/* User-invoked current-tab capture. No navigation, Apply clicks or account data.
 * Failed captures return structural diagnostics, never a whole-page fallback.
 */
(async () => {
  const result = {schema_version: 1, portal: "indeed", captured_at: new Date().toISOString(),
    page_kind: "unsupported", jobs: [], diagnostics: {reason_code: "unsupported_job_route", attempts: 0}};
  const diagnostic = result.diagnostics;
  let address;
  try { address = new URL(location.href); } catch (_) { return result; }
  const allowed = url => url.protocol === "https:" && !url.username && !url.password &&
    (!url.port || url.port === "443") &&
    (url.hostname === "indeed.com" || url.hostname.endsWith(".indeed.com")) &&
    !["secure.indeed.com", "auth.indeed.com", "accounts.indeed.com"].includes(url.hostname);
  if (!allowed(address)) { diagnostic.reason_code = "unsupported_origin"; return result; }
  const detailRoute = url => ["/viewjob", "/m/viewjob"].includes(url.pathname);
  diagnostic.route_kind = detailRoute(address) ? "detail" : ["/jobs", "/"].includes(address.pathname) ? "search" : "other";
  const jobUrl = raw => {
    try {
      if (typeof raw !== "string" || !raw.trim()) return "";
      const url = new URL(raw, address.href);
      if (!allowed(url) || !["/viewjob", "/rc/clk", "/jobs", "/", "/m/viewjob"].includes(url.pathname)) return "";
      const keys = url.searchParams.getAll("jk"), selected = url.searchParams.getAll("vjk");
      if (keys.length > 1 || selected.length > 1 ||
          (keys.length && selected.length && keys[0] !== selected[0])) return "";
      const id = keys[0] || selected[0] || "";
      return /^[a-f0-9]{16}$/i.test(id) ? url.origin + "/viewjob?jk=" + id.toLowerCase() : "";
    } catch (_) { return ""; }
  };
  const clip = (value, max = 300) => typeof value === "string" ? value.trim().slice(0, max) : "";
  const read = (root, selectors, max = 300) => {
    for (const selector of selectors) {
      const node = root.querySelector(selector);
      const text = clip(node?.innerText || node?.textContent || "", max);
      if (text) return text;
    }
    return "";
  };
  const normalized = value => value.normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
  const structuredJob = currentUrl => {
    const matches = new Map();
    let visited = 0;
    const visit = (item, depth = 0) => {
      if (!item || typeof item !== "object" || depth > 8 || ++visited > 400) return;
      if (Array.isArray(item)) { item.slice(0, 40).forEach(value => visit(value, depth + 1)); return; }
      const type = item["@type"];
      if (type === "JobPosting" || (Array.isArray(type) && type.includes("JobPosting"))) {
        const reference = item.url || (typeof item.mainEntityOfPage === "string" ? item.mainEntityOfPage : item.mainEntityOfPage?.["@id"]);
        if (jobUrl(reference) === currentUrl) {
          const candidate = {title: clip(item.title), company: clip(item.hiringOrganization?.name),
            html: clip(item.description, 25000)};
          if (candidate.title && candidate.company && candidate.html) matches.set(JSON.stringify(candidate), candidate);
        }
      }
      visit(item["@graph"], depth + 1);
    };
    const scripts = Array.from(document.querySelectorAll('script[type="application/ld+json"]')).slice(0, 10);
    for (const script of scripts) {
      const text = script.textContent || "";
      if (text.length > 250000) continue;
      try { visit(JSON.parse(text)); } catch (_) { /* Ignore malformed/unrelated metadata. */ }
    }
    diagnostic.structured_scripts_checked = scripts.length;
    diagnostic.matching_structured_jobs = Math.min(matches.size, 400);
    return matches.size === 1 ? [...matches.values()][0] : null;
  };
  // Only dedicated routes can yield a complete JD. Selected search panels can
  // lag their URLs and are deliberately excluded from every fallback.
  if (detailRoute(address)) {
    result.page_kind = "detail";
    const url = jobUrl(address.href);
    diagnostic.job_identity_valid = Boolean(url);
    if (!url) { diagnostic.reason_code = "job_identity_missing_or_conflicting"; return result; }
    for (let attempt = 0; attempt < 4; attempt++) {
      diagnostic.attempts = attempt + 1;
      const current = new URL(location.href);
      if (!detailRoute(current) || jobUrl(current.href) !== url) {
        diagnostic.reason_code = "job_changed_during_capture"; return result;
      }
      diagnostic.document_ready_state = ["loading", "interactive", "complete"].includes(document.readyState) ? document.readyState : "unknown";
      const pageHeading = read(document, ["h1", "h2"], 300);
      const pageLabel = clip(document.title, 300) + " " + pageHeading;
      diagnostic.browser_challenge_present = /\b(just a moment|verify you are human|access denied|security verification)\b/i.test(pageLabel) ||
        Boolean(document.querySelector("#challenge-running, iframe[src*='captcha'], [data-testid='captcha']"));
      diagnostic.job_unavailable_present = /\b(job (?:is )?(?:no longer available|not found|has expired)|job posting (?:has )?expired)\b/i.test(pageLabel);
      if (diagnostic.browser_challenge_present || diagnostic.job_unavailable_present) {
        diagnostic.reason_code = diagnostic.browser_challenge_present ? "browser_challenge_detected" : "job_unavailable"; return result;
      }
      diagnostic.layout_variant = document.querySelector("[data-testid='vj-job-title']") ? "viewjob_vj" : "legacy_or_unknown";
      let title = read(document, ["[data-testid='viewjob-main-content'] [data-testid='vj-job-title']",
        ".jobsearch-JobInfoHeader-title", "[data-testid='jobsearch-JobInfoHeader-title']", "h1"]);
      let description = read(document, ["[data-testid='viewjob-job-content'] .simple-job-description-html",
        "#jobDescriptionText", "[data-testid='jobDescriptionText']", "[data-testid='jobsearch-jobDescriptionText']"], 25000);
      let company = read(document, ["[data-testid='viewjob-main-content'] [data-testid='company-info-metadata'] a[href*='/cmp/']",
        "[data-testid='inlineHeader-companyName']", "[data-testid='company-name']", ".companyName"]);
      const structured = structuredJob(url);
      diagnostic.title_present = Boolean(title);
      diagnostic.company_present = Boolean(company);
      diagnostic.dom_description_characters = description.length;
      diagnostic.description_source = description ? "dedicated_job_container" : "none";
      if (description.length < 200 && structured) {
        if ((title && normalized(title) !== normalized(structured.title)) ||
            (company && normalized(company) !== normalized(structured.company))) {
          diagnostic.reason_code = "structured_job_header_mismatch"; return result;
        }
        const doc = new DOMParser().parseFromString(structured.html, "text/html");
        doc.querySelectorAll("script, style").forEach(node => node.remove());
        const text = clip(doc.body?.textContent || "", 25000);
        if (text.length >= 200) {
          description = text; title = title || structured.title; company = company || structured.company;
          diagnostic.description_source = "matching_job_structured_data";
        }
      }
      diagnostic.title_present = Boolean(title);
      diagnostic.company_present = Boolean(company);
      diagnostic.description_characters = description.length;
      if (title && description.length >= 200) {
        result.jobs.push({url, title, description, company, capture_kind: "detail",
          location: read(document, ["[data-testid='inlineHeader-companyLocation']", "[data-testid='text-location']", ".companyLocation"])});
        diagnostic.reason_code = "job_captured"; return result;
      }
      diagnostic.reason_code = diagnostic.matching_structured_jobs > 1 ? "structured_job_ambiguous" :
        !title ? "job_title_missing" : !description ? "job_description_missing" : "job_description_incomplete";
      // Let a delayed job component hydrate; never poll forever or click a
      // control. Identity is checked again before every subsequent read.
      if (attempt < 3) await new Promise(resolve => setTimeout(resolve, 400));
    }
    return result;
  }
  if (!["/jobs", "/"].includes(address.pathname)) return result;
  const seen = new Set();
  const cards = Array.from(document.querySelectorAll(".job_seen_beacon, [data-testid='slider_item'], li[data-jk]")).slice(0, 75);
  diagnostic.cards_seen = cards.length;
  for (const card of cards) {
    const link = card.querySelector("h2.jobTitle a, a.jcs-JobTitle, a[data-jk]");
    const url = jobUrl(link?.getAttribute("href") || "");
    const title = clip(link?.innerText || link?.textContent || "");
    if (!url || !title || seen.has(url)) continue;
    seen.add(url);
    result.jobs.push({url, title, description: "", capture_kind: "search",
      company: read(card, ["[data-testid='company-name']", ".companyName"]),
      location: read(card, ["[data-testid='text-location']", ".companyLocation"])});
  }
  result.page_kind = "search";
  diagnostic.reason_code = result.jobs.length ? "search_metadata_only" : "search_posting_links_missing";
  return result;
})();
