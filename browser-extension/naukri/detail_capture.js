/* Read-only job detail extraction. Invoked only on Naukri tabs opened for an
 * explicitly requested batch. Returns no credentials, cookies or profile data.
 */
(() => {
  const empty = { title: "", company: "", location: "", description: "", url: "" };
  let parsed;
  try { parsed = new URL(location.href); } catch (_) { return empty; }
  const host = parsed.hostname.toLowerCase();
  if (
    parsed.protocol !== "https:" ||
    !(host === "naukri.com" || host.endsWith(".naukri.com")) ||
    !/^\/job-listings(?:-|\/)/.test(parsed.pathname) || parsed.username || parsed.password ||
    (parsed.port && parsed.port !== "443")
  ) return empty;

  const clipped = (value, max = 25000) => String(value || "").trim().slice(0, max);
  // Kept self-contained for isolated script injection; same conservative rule
  // as the current-tab capture and Python importer's clean_company_name.
  const cleanCompany = value => {
    const raw = clipped(value, 300), lines = raw.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
    const review = /^(?:\d[\d.,\sKkMmBb]*\s*Reviews?|\(\d[\d.,\sKkMmBb]*\s*Reviews?\))$/i;
    const rating = /^(?:[0-4](?:\.\d+)?|5(?:\.0+)?)$/;
    const suffix = lines.slice(1);
    return suffix.some(line => review.test(line)) && suffix.every(line => review.test(line) || rating.test(line)) ? lines[0] : raw;
  };
  const selectText = (selectors, max = 25000) => {
    for (const selector of selectors) {
      const node = document.querySelector(selector);
      const value = node ? clipped(node.innerText || node.textContent, max) : "";
      if (value) return value;
    }
    return "";
  };
  const htmlText = (html) => {
    const doc = new DOMParser().parseFromString(String(html || ""), "text/html");
    return clipped(doc.body ? doc.body.textContent : "");
  };
  const samePosting = (raw) => {
    try {
      if (typeof raw !== "string" || !raw.trim()) return false;
      const target = new URL(raw, parsed.href);
      return target.protocol === "https:" && !target.username && !target.password &&
        target.origin === parsed.origin && target.pathname === parsed.pathname;
    } catch (_) { return false; }
  };
  const jobPosting = (item, depth = 0) => {
    if (!item || typeof item !== "object" || depth > 8) return null;
    if (Array.isArray(item)) {
      for (const nested of item.slice(0, 40)) {
        const found = jobPosting(nested, depth + 1);
        if (found) return found;
      }
      return null;
    }
    const type = item["@type"];
    if (type === "JobPosting" || (Array.isArray(type) && type.includes("JobPosting"))) {
      const reference = item.url || (typeof item.mainEntityOfPage === "string" ? item.mainEntityOfPage : item.mainEntityOfPage?.["@id"]);
      if (samePosting(reference)) return item;
    }
    return jobPosting(item["@graph"], depth + 1);
  };
  let structured = null;
  for (const script of Array.from(document.querySelectorAll('script[type="application/ld+json"]')).slice(0, 10)) {
    try {
      const text = script.textContent || "";
      if (text.length > 250000) continue;
      structured = jobPosting(JSON.parse(text));
      if (structured) break;
    } catch (_) { /* Ignore unrelated or malformed JSON-LD. */ }
  }
  const structuredOrg = structured && structured.hiringOrganization;
  const structuredLoc = structured && structured.jobLocation;
  const structuredAddress = (structuredLoc && !Array.isArray(structuredLoc)) ? structuredLoc.address : null;
  const title = selectText([
    "h1", ".jd-header-title", '[class*="jd-header-title"]', '[class*="job-title"]'
  ], 300) || clipped(structured && structured.title, 300);
  const company = cleanCompany(selectText([
    ".jd-header-comp-name", '[class*="jd-header-comp-name"]',
    '[class*="comp-name"]', '[class*="company-name"]'
  ], 300) || clipped(structuredOrg && structuredOrg.name, 300));
  const loc = selectText([
    ".location", '[class*="location"]', '[class*="loc-"]'
  ], 300) || clipped(structuredAddress && (
    structuredAddress.addressLocality || structuredAddress.addressRegion
  ), 300);
  const domDescription = selectText([
    '[class*="dang-inner-html"]', ".job-desc", ".job-description",
    '[class*="job-desc"]', '[class*="jobDescription"]'
  ]);
  const richDescription = structured && structured.description ? htmlText(structured.description) : "";
  const description = domDescription.length >= 200 ? domDescription :
    (richDescription.length >= 200 ? richDescription : domDescription);
  return {
    title, company, location: loc, description: clipped(description),
    url: parsed.origin + parsed.pathname
  };
})();
