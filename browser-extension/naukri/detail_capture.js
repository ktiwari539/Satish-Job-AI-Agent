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
    !parsed.pathname.includes("job-listings")
  ) return empty;

  const clipped = (value, max = 25000) => String(value || "").trim().slice(0, max);
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
  const jobPosting = (item) => {
    if (!item || typeof item !== "object") return null;
    if (Array.isArray(item)) {
      for (const nested of item) {
        const found = jobPosting(nested);
        if (found) return found;
      }
      return null;
    }
    const type = item["@type"];
    if (type === "JobPosting" || (Array.isArray(type) && type.includes("JobPosting"))) return item;
    return jobPosting(item["@graph"]);
  };
  let structured = null;
  for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      structured = jobPosting(JSON.parse(script.textContent || ""));
      if (structured) break;
    } catch (_) { /* Ignore unrelated or malformed JSON-LD. */ }
  }
  const structuredOrg = structured && structured.hiringOrganization;
  const structuredLoc = structured && structured.jobLocation;
  const structuredAddress = (structuredLoc && !Array.isArray(structuredLoc)) ? structuredLoc.address : null;
  const title = selectText([
    "h1", ".jd-header-title", '[class*="jd-header-title"]', '[class*="job-title"]'
  ], 300) || clipped(structured && structured.title, 300);
  const company = selectText([
    ".jd-header-comp-name", '[class*="jd-header-comp-name"]',
    '[class*="comp-name"]', '[class*="company-name"]'
  ], 300) || clipped(structuredOrg && structuredOrg.name, 300);
  const loc = selectText([
    ".location", '[class*="location"]', '[class*="loc-"]'
  ], 300) || clipped(structuredAddress && (
    structuredAddress.addressLocality || structuredAddress.addressRegion
  ), 300);
  const domDescription = selectText([
    '[class*="dang-inner-html"]', ".job-desc", ".job-description",
    '[class*="job-desc"]', '[class*="jobDescription"]'
  ]);
  const richDescription = htmlText(structured && structured.description);
  const description = domDescription.length >= 200 ? domDescription :
    (richDescription.length >= 200 ? richDescription : domDescription);
  return {
    title, company, location: loc, description: clipped(description),
    url: parsed.origin + parsed.pathname
  };
})();
