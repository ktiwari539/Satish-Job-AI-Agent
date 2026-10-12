/* Explicitly requested, read-only browser-side JD enrichment.
 * Does not access authentication state, Google, profile data, forms or Apply.
 */
const BATCH_LIMIT = 20;
let batchRunning = false;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

function safeJobUrl(raw) {
  try {
    const url = new URL(raw);
    const hostname = url.hostname.toLowerCase();
    if (url.protocol !== "https:" ||
        !(hostname === "naukri.com" || hostname.endsWith(".naukri.com")) ||
        !url.pathname.includes("job-listings") ||
        url.username || url.password ||
        (url.port && url.port !== "443")) return "";
    return url.origin + url.pathname;
  } catch (_) {
    return "";
  }
}

async function awaitTabReady(tabId) {
  for (let attempt = 0; attempt < 20; attempt++) {
    try {
      const tab = await chrome.tabs.get(tabId);
      if (tab.status === "complete") return true;
    } catch (_) {
      return false;
    }
    await pause(500);
  }
  return false;
}

async function getDescription(job) {
  let tab;
  try {
    tab = await chrome.tabs.create({ url: job.url, active: false });
    await awaitTabReady(tab.id);
    for (let retry = 0; retry < 4; retry++) {
      await pause(retry === 0 ? 800 : 900);
      const current = await chrome.tabs.get(tab.id);
      if (safeJobUrl(current.url || "") !== job.url) {
        // Redirected away from the exact requested posting: do not capture it.
        return null;
      }
      const result = await chrome.scripting.executeScript({
        target: { tabId: tab.id }, files: ["detail_capture.js"]
      });
      const detail = result?.[0]?.result;
      if (detail && safeJobUrl(detail.url) === job.url &&
          typeof detail.description === "string" &&
          detail.description.length >= 200) return detail;
    }
    return null;
  } catch (_) {
    // Missing/blocked/incompatible pages stay unqualified, never inferred.
    return null;
  } finally {
    if (tab && Number.isInteger(tab.id)) {
      try { await chrome.tabs.remove(tab.id); } catch (_) { /* Closed by user */ }
    }
  }
}

async function exportBatch(rawJobs) {
  const candidates = [];
  const seen = new Set();
  for (const record of Array.isArray(rawJobs) ? rawJobs.slice(0, BATCH_LIMIT) : []) {
    const url = safeJobUrl(record && record.url);
    if (!url || seen.has(url)) continue;
    seen.add(url);
    candidates.push({
      url, title: String(record.title || "").slice(0, 300),
      company: String(record.company || "").slice(0, 300),
      location: String(record.location || "").slice(0, 300),
    });
  }
  if (!candidates.length) throw Error("No supported Naukri job links found.");

  const jobs = [];
  let fullDescriptions = 0;
  for (const job of candidates) {
    const detail = await getDescription(job);
    const complete = Boolean(detail && detail.description.length >= 200);
    if (complete) fullDescriptions++;
    jobs.push({
      title: complete ? (detail.title || job.title).slice(0, 300) : job.title,
      company: complete ? (detail.company || job.company).slice(0, 300) : job.company,
      location: complete ? (detail.location || job.location).slice(0, 300) : job.location,
      url: job.url,
      description: complete ? detail.description.slice(0, 25000) : "",
      capture_kind: "detail"
    });
    // Conservative pacing; never click application, security or account controls.
    await pause(700);
  }
  const payload = {
    schema_version: 1, portal: "naukri", captured_at: new Date().toISOString(),
    page_kind: "detail", jobs
  };
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const encoded = encodeURIComponent(JSON.stringify(payload, null, 2));
  await chrome.downloads.download({
    url: "data:application/json;charset=utf-8," + encoded,
    filename: "naukri-jobs-details-" + stamp + ".json",
    conflictAction: "uniquify",
    saveAs: false
  });
  return { status: "exported", visited: jobs.length, full_jd: fullDescriptions,
           needing_full_jd: jobs.length - fullDescriptions };
}

chrome.runtime.onMessage.addListener((message, _sender, reply) => {
  if (!message || message.action !== "naukri_enrich_jds") return false;
  if (batchRunning) {
    reply({ status: "blocked", reason: "batch_already_running" });
    return false;
  }
  batchRunning = true;
  exportBatch(message.jobs)
    .then(result => reply(result))
    .catch(error => reply({
      status: "error",
      reason: error && error.message ? error.message : "batch_failed"
    }))
    .finally(() => { batchRunning = false; });
  return true;
});
