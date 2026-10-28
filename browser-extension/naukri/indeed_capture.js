/* User-invoked current-tab capture. No navigation, Apply clicks or account data. */
(() => {
  const result = {schema_version: 1, portal: "indeed", captured_at: new Date().toISOString(),
    page_kind: "unsupported", jobs: []};
  const address = new URL(location.href);
  const allowed = url => url.protocol === "https:" && !url.username && !url.password &&
    (!url.port || url.port === "443") &&
    (url.hostname === "indeed.com" || url.hostname.endsWith(".indeed.com")) &&
    !["secure.indeed.com", "auth.indeed.com", "accounts.indeed.com"].includes(url.hostname);
  if (!allowed(address)) return result;
  const jobUrl = raw => {
    try {
      const url = new URL(raw, address.href);
      if (!allowed(url) || !["/viewjob", "/rc/clk", "/jobs", "/", "/m/viewjob"].includes(url.pathname)) return "";
      const keys = url.searchParams.getAll("jk"), selected = url.searchParams.getAll("vjk");
      if (keys.length > 1 || selected.length > 1 ||
          (keys.length && selected.length && keys[0] !== selected[0])) return "";
      const id = keys[0] || selected[0] || "";
      return /^[a-f0-9]{16}$/i.test(id) ? url.origin + "/viewjob?jk=" + id.toLowerCase() : "";
    } catch (_) { return ""; }
  };
  const read = (root, selectors, max = 300) => {
    for (const selector of selectors) {
      const node = root.querySelector(selector);
      const text = String(node?.innerText || node?.textContent || "").trim().slice(0, max);
      if (text) return text;
    }
    return "";
  };
  // Only a dedicated job route can certify a complete JD. A selected search
  // panel can lag its URL; export search cards until its identity is verified.
  if (["/viewjob", "/m/viewjob"].includes(address.pathname)) {
    const url = jobUrl(address.href);
    const title = read(document, [".jobsearch-JobInfoHeader-title", "[data-testid='jobsearch-JobInfoHeader-title']", "h1"]);
    const description = read(document, ["#jobDescriptionText"], 25000);
    if (url && title && description) {
      result.page_kind = "detail";
      result.jobs.push({url, title, description, capture_kind: "detail",
        company: read(document, ["[data-testid='inlineHeader-companyName']", "[data-testid='company-name']", ".companyName"]),
        location: read(document, ["[data-testid='inlineHeader-companyLocation']", "[data-testid='text-location']", ".companyLocation"])});
    }
    return result;
  }
  if (!["/jobs", "/"].includes(address.pathname)) return result;
  const seen = new Set();
  for (const card of Array.from(document.querySelectorAll(".job_seen_beacon, [data-testid='slider_item'], li[data-jk]")).slice(0, 75)) {
    const link = card.querySelector("h2.jobTitle a, a.jcs-JobTitle, a[data-jk]");
    const url = jobUrl(link?.getAttribute("href") || "");
    const title = String(link?.innerText || link?.textContent || "").trim().slice(0, 300);
    if (!url || !title || seen.has(url)) continue;
    seen.add(url);
    result.jobs.push({url, title, description: "", capture_kind: "search",
      company: read(card, ["[data-testid='company-name']", ".companyName"]),
      location: read(card, ["[data-testid='text-location']", ".companyLocation"])});
  }
  result.page_kind = "search";
  return result;
})();
