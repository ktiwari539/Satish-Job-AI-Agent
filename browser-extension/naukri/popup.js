/* User-invoked, job-only capture. Chrome executes this solely on the current tab. */
function captureNaukriJobs() {
  const clip = (value, length = 25000) => String(value || "").trim().slice(0, length);
  // Match the conservative importer rule: only discard an all-numeric
  // rating/review suffix on separate lines, never words in the company name.
  const cleanCompany = value => {
    const raw = clip(value, 300), lines = raw.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
    const review = /^(?:\d[\d.,\sKkMmBb]*\s*Reviews?|\(\d[\d.,\sKkMmBb]*\s*Reviews?\))$/i;
    const rating = /^(?:[0-4](?:\.\d+)?|5(?:\.0+)?)$/;
    const suffix = lines.slice(1);
    return suffix.some(line => review.test(line)) && suffix.every(line => review.test(line) || rating.test(line)) ? lines[0] : raw;
  };
  const read = (root, selectors, length = 500) => {
    for (const selector of selectors) {
      const node = root.querySelector(selector);
      const value = clip(node && (node.innerText || node.textContent), length);
      if (value) return value;
    }
    return "";
  };
  const allowedHost = (host) => host === "naukri.com" || host.endsWith(".naukri.com");
  const safeUrl = (raw) => {
    try {
      if (typeof raw !== "string" || !raw.trim()) return "";
      const url = new URL(raw, location.href);
      if (url.protocol !== "https:" || !allowedHost(url.hostname) || url.username || url.password ||
          (url.port && url.port !== "443") || !/^\/job-listings(?:-|\/)/.test(url.pathname)) return "";
      return url.origin + url.pathname;
    } catch (_) { return ""; }
  };
  if (!allowedHost(location.hostname) || location.protocol !== "https:") {
    return { schema_version: 1, portal: "naukri", captured_at: new Date().toISOString(), page_kind: "unsupported", jobs: [] };
  }
  const isDetail = /^\/job-listings(?:-|\/)/.test(location.pathname);
  const jobs = [];
  const diagnostics = {cards_seen: 0, missing_posting_links: 0, ambiguous_posting_links: 0, duplicate_posting_links: 0};
  const seen = new Set();
  const cards = document.querySelectorAll("article.jobTuple, div.srp-jobtuple-wrapper, div.cust-job-tuple");
  if (!isDetail && cards.length) {
    for (const card of Array.from(cards).slice(0, 75)) {
      diagnostics.cards_seen++;
      const urls = new Set();
      for (const node of [card, ...Array.from(card.querySelectorAll("a[href], [data-url], [data-href]")).slice(0, 30)]) {
        for (const name of ["href", "data-url", "data-href"]) {
          const candidate = safeUrl(node.getAttribute(name));
          if (candidate) urls.add(candidate);
        }
      }
      if (urls.size !== 1) {
        diagnostics[urls.size ? "ambiguous_posting_links" : "missing_posting_links"]++;
        continue;
      }
      const url = Array.from(urls)[0];
      const title = read(card, ["a.title", "a[title]", ".title"], 300);
      if (!title || !url) continue;
      if (seen.has(url)) { diagnostics.duplicate_posting_links++; continue; }
      seen.add(url);
      jobs.push({
        title, company: cleanCompany(read(card, ["a.comp-name", ".comp-name", ".subTitle"], 300)),
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
    if (title && description && safeUrl(location.href)) {
      jobs.push({
        title, company: cleanCompany(read(document, [".jd-header-comp-name", "[class*='comp-name']", "[class*='company-name']"], 300)),
        location: read(document, [".location", ".loc", "[class*='loc-']"], 300),
        url: safeUrl(location.href), description, capture_kind: "detail"
      });
    }
  }
  return {
    schema_version: 1, portal: "naukri", captured_at: new Date().toISOString(),
    page_kind: isDetail ? "detail" : "search", jobs, diagnostics
  };
}

const button = document.getElementById("capture");
const status = document.getElementById("status");
document.getElementById("version").textContent = "Version " + chrome.runtime.getManifest().version;
function currentPortal(raw) {
  try {
    const url = new URL(raw);
    if (url.protocol !== "https:" || url.username || url.password ||
        (url.port && url.port !== "443")) return "";
    for (const portal of ["naukri", "indeed"]) {
      if (url.hostname === portal + ".com" || url.hostname.endsWith("." + portal + ".com")) {
        if (portal === "indeed" && ["secure.indeed.com", "auth.indeed.com", "accounts.indeed.com"].includes(url.hostname)) return "";
        return portal;
      }
    }
  } catch (_) { /* Unsupported site. */ }
  return "";
}
button.addEventListener("click", async () => {
  button.disabled = true;
  status.textContent = "Reading the selected job tab…";
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const portal = currentPortal(tab?.url || "");
    if (!tab || !portal) {
      throw new Error("Open a Naukri or Indeed job-description/search tab first.");
    }
    const results = await chrome.scripting.executeScript(portal === "naukri" ? {
      target: {tabId: tab.id}, func: captureNaukriJobs
    } : {target: {tabId: tab.id}, files: ["indeed_capture.js"]});
    const payload = results[0] && results[0].result;
    if (!payload || payload.portal !== portal || !Array.isArray(payload.jobs)) {
      throw new Error("No supported jobs found. Try a search-results or individual job page.");
    }
    if (!payload.jobs.length && !payload.diagnostics) {
      throw Error("No complete job found. Open the full job description in its own tab, then export.");
    }
    if (payload.page_kind === "detail" && payload.jobs.length === 1) {
      const inspected = await chrome.scripting.executeScript({target: {tabId: tab.id}, files: ["application_inspection.js"]});
      const report = inspected?.[0]?.result;
      if (!report || report.mode !== "READ_ONLY_INSPECTION" || report.portal !== portal || report.job_url !== payload.jobs[0].url) {
        throw Error("The selected job changed or its application controls could not be correlated. No export created.");
      }
      payload.application_inspection = report;
    }
    payload.extension_version = chrome.runtime.getManifest().version;
    payload.capture_summary = {
      scope: payload.page_kind === "search" ? "search_metadata_only" : "job_detail_and_page_controls",
      jobs: payload.jobs.length,
      nonempty_descriptions: payload.jobs.filter(job => typeof job.description === "string" && job.description.trim()).length,
      application_control_inspections: payload.application_inspection ? 1 : 0,
      application_form_exercised: false, application_ready: false, submission_enabled: false
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    anchor.href = url;
    anchor.download = portal + "-jobs-" + (payload.jobs.length ? "" : "diagnostics-") + stamp + ".json";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    if (!payload.jobs.length) {
      status.textContent = "No verified posting links on this page. Saved counts-only diagnostics. Open a job title to its full description, then export there.";
    } else if (payload.page_kind === "search") {
      status.textContent = "Exported " + payload.jobs.length + " SEARCH listings only; no full descriptions or application inspection. " +
        "Open one job's full description in its own tab, then use this first button again. No Apply click is needed.";
    } else {
      status.textContent = "Exported this job's description and page-control inspection. The JSON is in Downloads. " +
        "This does not verify an application form, resume or readiness to submit.";
    }
  } catch (error) {
    status.textContent = error && error.message ? error.message : "Capture failed.";
  } finally {
    button.disabled = false;
  }
});

/* Optional read-only batch. One explicit click per capture; never auto-submits. */
const enrichButton = document.getElementById("enrich");
const indeedOrigins = {origins: ["https://*.indeed.com/*"]};
document.getElementById("enable-indeed").addEventListener("click", async () => {
  try {
    // Use a normal extension tab so a native permission prompt cannot discard
    // the setup result when Chrome closes the toolbar popup.
    await chrome.tabs.create({url: chrome.runtime.getURL("indeed-access.html"), active: true});
    status.textContent = "Setup opened in a new tab. Choose Enable Indeed access there; then return to your job tab.";
  } catch (_) {
    status.textContent = "Could not open Indeed access setup. Reload this extension once. You can still open one full job and use Export current job / search.";
  }
});
enrichButton.addEventListener("click", async () => {
  enrichButton.disabled = true;
  button.disabled = true;
  status.textContent = "Checking this job search page…";
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const portal = currentPortal(tab?.url || "");
    if (!portal) {
      throw Error("Open a Naukri or Indeed search-results page in regular Chrome first.");
    }
    if (portal === "indeed" && !(await chrome.permissions.contains(indeedOrigins))) {
      throw Error("Use Set up Indeed batch access first. Or open one full job in its own tab and choose Export current job / search; that needs no batch access.");
    }
    const captured = await chrome.scripting.executeScript(portal === "naukri" ? {
      target: {tabId: tab.id}, func: captureNaukriJobs
    } : {target: {tabId: tab.id}, files: ["indeed_capture.js"]});
    const payload = captured[0]?.result;
    if (payload?.page_kind === "detail") {
      throw Error("This is an individual job page. Choose Export current job / search (the first button) to export this job.");
    }
    if (!payload || payload.page_kind !== "search" || !payload.jobs?.length) {
      const homepage = portal === "naukri" && new URL(tab.url).pathname.startsWith("/mnjuser/");
      throw Error((homepage ? "These Naukri recommendations have no verified posting links. " : "No verified posting links were found here. ") +
        "Close this popup, open one job title to its full description, then click the extension and choose Export current job / search (the first button). Do not click Apply.");
    }
    status.textContent =
      "Reading up to 20 full descriptions in inactive " + portal + " tabs. " +
      "Keep this popup open; this may take a minute or two.";
    const outcome = await chrome.runtime.sendMessage({
      action: "portal_enrich_jds", portal,
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

/* Explicit, read-only inspection of one job's application controls.
 * No buttons are clicked, no form values are read, and no applications made.
 */
const inspectButton = document.getElementById("inspect");
inspectButton.addEventListener("click", async () => {
  inspectButton.disabled = true;
  status.textContent = "Inspecting application controls without interacting…";
  try {
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    const portal = currentPortal(tab?.url || "");
    if (!portal) {
      throw Error("Open an individual Naukri or Indeed job-description page first.");
    }
    const inspected = await chrome.scripting.executeScript({
      target: {tabId: tab.id}, files: ["application_inspection.js"]
    });
    const report = inspected?.[0]?.result;
    if (!report || report.mode !== "READ_ONLY_INSPECTION" || !report.job_url) {
      throw Error("Could not inspect this job page.");
    }
    // JSON contains only application control categories, field types and booleans.
    const blob = new Blob([JSON.stringify(report, null, 2)], {type: "application/json"});
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = portal + "-application-inspection-" +
      new Date().toISOString().replace(/[:.]/g, "-") + ".json";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 10000);
    status.textContent = "Read-only inspection exported. Controls: " +
      (report.application_controls.join(", ") || "none detected") +
      "; required input types: " +
      (report.required_field_types.join(", ") || "none detected") +
      ". No application was submitted.";
  } catch (error) {
    status.textContent = error?.message || "Inspection failed.";
  } finally {
    inspectButton.disabled = false;
  }
});

/* Manual, short-lived association of one known Naukri job to an external ATS.
 * Never clicks Apply; no OAuth, cookies, or arbitrary site permissions.
 */
const handoffKey = "naukri_ats_handoff_v1";
const handoffTtlMs = 15 * 60 * 1000;
const handoffButton = document.getElementById("handoff");
const inspectATSButton = document.getElementById("inspect-ats");

handoffButton.addEventListener("click", async () => {
  handoffButton.disabled = true;
  status.textContent = "Saving the current Naukri job for supervised review…";
  try {
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    const url = new URL(tab?.url || "");
    if (url.protocol !== "https:" ||
        !(url.hostname === "naukri.com" || url.hostname.endsWith(".naukri.com")) ||
        !url.pathname.includes("job-listings")) {
      throw Error("Open the specific Naukri job description first.");
    }
    const source_job_url = url.origin + url.pathname;
    await chrome.storage.session.set({
      [handoffKey]: {source_job_url, created_at: Date.now()}
    });
    status.textContent =
      "Job selected for 15 minutes. On the Naukri tab, MANUALLY click " +
      "'Apply on company website' only if it clearly navigates to the employer. " +
      "Do not automate one-click Apply/Submit. Once on an external hiring form, " +
      "open this extension there and choose 'Inspect employer ATS form'.";
  } catch (error) {
    status.textContent = error?.message || "Could not prepare external Apply review.";
  } finally {
    handoffButton.disabled = false;
  }
});

inspectATSButton.addEventListener("click", async () => {
  inspectATSButton.disabled = true;
  status.textContent = "Checking the selected hiring page without reading entered values…";
  try {
    const state = await chrome.storage.session.get(handoffKey);
    const handoff = state?.[handoffKey];
    if (!handoff || !Number.isFinite(handoff.created_at) ||
        Date.now() < handoff.created_at ||
        Date.now() - handoff.created_at > handoffTtlMs ||
        typeof handoff.source_job_url !== "string") {
      throw Error("No fresh Naukri handoff found. Return to the job and click Prepare external Apply review.");
    }
    const source = new URL(handoff.source_job_url);
    if (source.protocol !== "https:" ||
        !(source.hostname === "naukri.com" || source.hostname.endsWith(".naukri.com")) ||
        !source.pathname.includes("job-listings") ||
        source.search || source.hash) {
      throw Error("The saved job reference is not valid.");
    }
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    const url = new URL(tab?.url || "");
    if (url.protocol !== "https:" ||
        url.hostname === "naukri.com" || url.hostname.endsWith(".naukri.com") ||
        url.username || url.password) {
      throw Error("Open the employer ATS page reached from Naukri before inspecting.");
    }
    const inspected = await chrome.scripting.executeScript({
      target: {tabId: tab.id}, files: ["ats_form_inspection.js"]
    });
    const report = inspected?.[0]?.result;
    if (!report || report.mode !== "READ_ONLY_FORM_INSPECTION" ||
        report.status !== "read_only_inspection") {
      throw Error("This page was not recognized as a supported employer hiring form. Do not provide credentials.");
    }
    if (report.site_origin !== url.origin) {
      throw Error("The hiring page changed during inspection; try again on the destination tab.");
    }
    report.source_naukri_job_url = handoff.source_job_url;
    // This is a user-reported association, not browser-proven click provenance.
    report.handoff_method = "user_reported_external_apply";
    report.handoff_navigation_verified = false;
    const blob = new Blob([JSON.stringify(report, null, 2)], {type: "application/json"});
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = "naukri-ats-form-inspection-" +
      new Date().toISOString().replace(/[:.]/g, "-") + ".json";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 10000);
    await chrome.storage.session.remove(handoffKey);
    status.textContent = "Read-only ATS inspection exported (" + report.fields.length +
      " visible fields, " + report.action_controls.join(", ") +
      "). Nothing was filled or submitted. Review the JSON before sharing it.";
  } catch (error) {
    status.textContent = error?.message || "External form inspection failed.";
  } finally {
    inspectATSButton.disabled = false;
  }
});
