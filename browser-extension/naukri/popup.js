/* User-invoked, job-only capture. Chrome executes this solely on the current tab. */
function captureNaukriJobs() {
  const clip = (value, length = 25000) => String(value || "").trim().slice(0, length);
  const read = (root, selectors, length = 500) => {
    for (const selector of selectors) {
      const node = root.querySelector(selector);
      const value = clip(node && (node.innerText || node.textContent), length);
      if (value) return value;
    }
    return "";
  };
  const attr = (root, selectors, property) => {
    for (const selector of selectors) {
      const node = root.querySelector(selector);
      if (node) {
        const value = node.getAttribute(property);
        if (value) return value;
      }
    }
    return "";
  };
  const allowedHost = (host) => host === "naukri.com" || host.endsWith(".naukri.com");
  const safeUrl = (raw) => {
    try {
      const url = new URL(raw, location.href);
      if (url.protocol !== "https:" || !allowedHost(url.hostname)) return "";
      return url.origin + url.pathname;
    } catch (_) { return ""; }
  };
  if (!allowedHost(location.hostname) || location.protocol !== "https:") {
    return { schema_version: 1, portal: "naukri", captured_at: new Date().toISOString(), page_kind: "unsupported", jobs: [] };
  }
  const isDetail = /job-listings/i.test(location.pathname);
  const jobs = [];
  const cards = document.querySelectorAll("article.jobTuple, div.srp-jobtuple-wrapper, div.cust-job-tuple");
  if (!isDetail && cards.length) {
    for (const card of Array.from(cards).slice(0, 75)) {
      const link = attr(card, ["a.title", "a[href*='job-listings']", "a[title]"], "href");
      const url = safeUrl(link);
      const title = read(card, ["a.title", "a[title]", ".title"], 300);
      if (!title || !url) continue;
      jobs.push({
        title, company: read(card, ["a.comp-name", ".comp-name", ".subTitle"], 300),
        location: read(card, [".locWdth", ".loc-wrap", ".location"], 300),
        url, description: "", capture_kind: "search"
      });
    }
  } else if (isDetail) {
    const description = read(document, [
      ".job-desc", ".job-description", "[class*='dang-inner-html']",
      "[class*='job-desc']", "[class*='jobDescription']", ".jobDetail"
    ], 25000);
    const title = read(document, [
      "h1", ".jd-header-title", "[class*='jd-header-title']", "[class*='job-title']"
    ], 300);
    if (title && description) {
      jobs.push({
        title, company: read(document, [".jd-header-comp-name", "[class*='comp-name']", "[class*='company-name']"], 300),
        location: read(document, [".location", ".loc", "[class*='loc-']"], 300),
        url: safeUrl(location.href), description, capture_kind: "detail"
      });
    }
  }
  return {
    schema_version: 1, portal: "naukri", captured_at: new Date().toISOString(),
    page_kind: isDetail ? "detail" : "search", jobs
  };
}

const button = document.getElementById("capture");
const status = document.getElementById("status");
button.addEventListener("click", async () => {
  button.disabled = true;
  status.textContent = "Reading the current Naukri tab…";
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !/^https:\/\/([^.\/]+\.)*naukri\.com\//i.test(tab.url || "")) {
      throw new Error("Open a Naukri search or job-description tab first.");
    }
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id }, func: captureNaukriJobs
    });
    const payload = results[0] && results[0].result;
    if (!payload || !payload.jobs || !payload.jobs.length) {
      throw new Error("No supported jobs found. Try a search-results or individual job page.");
    }
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    anchor.href = url;
    anchor.download = "naukri-jobs-" + stamp + ".json";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    status.textContent = "Exported " + payload.jobs.length + " job(s). The JSON is in Downloads.";
  } catch (error) {
    status.textContent = error && error.message ? error.message : "Capture failed.";
  } finally {
    button.disabled = false;
  }
});

/* Optional read-only batch. One explicit click per capture; never auto-submits. */
const enrichButton = document.getElementById("enrich");
enrichButton.addEventListener("click", async () => {
  enrichButton.disabled = true;
  button.disabled = true;
  status.textContent = "Checking this Naukri search page…";
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !/^https:\\/\\/([^.\\/]+\\.)*naukri\\.com\\//i.test(tab.url || "")) {
      throw Error("Open a Naukri search-results page in regular Chrome first.");
    }
    const captured = await chrome.scripting.executeScript({
      target: { tabId: tab.id }, func: captureNaukriJobs
    });
    const payload = captured[0]?.result;
    if (!payload || payload.page_kind !== "search" || !payload.jobs?.length) {
      throw Error("No Naukri search results found on this tab.");
    }
    status.textContent =
      "Reading up to 20 full descriptions in inactive Naukri tabs. " +
      "Keep this popup open; this may take a minute or two.";
    const outcome = await chrome.runtime.sendMessage({
      action: "naukri_enrich_jds",
      jobs: payload.jobs.slice(0, 20)
    });
    if (!outcome || outcome.status !== "exported") {
      throw Error(outcome?.reason || "Full description export failed.");
    }
    status.textContent =
      "Done: " + outcome.full_jd + " full descriptions from " + outcome.visited +
      " listings. The batch JSON is in Downloads. " +
      "Missing descriptions remain unqualified.";
  } catch (error) {
    status.textContent = error?.message || "Full-description capture failed.";
  } finally {
    enrichButton.disabled = false;
    button.disabled = false;
  }
});
