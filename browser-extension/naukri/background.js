/* Explicitly requested, bounded, read-only JD enrichment in ordinary Chrome. */
const BATCH_LIMIT = 20;
const BATCH_BUDGET_MS = 120000;
let batchRunning = false;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

function safeJobUrl(raw, portal = "naukri") {
  try {
    if (!["naukri", "indeed"].includes(portal) || typeof raw !== "string" || !raw.trim()) return "";
    const url = new URL(raw), host = url.hostname;
    if (url.protocol !== "https:" || url.username || url.password ||
        (url.port && url.port !== "443") ||
        !(host === portal + ".com" || host.endsWith("." + portal + ".com"))) return "";
    if (portal === "naukri") return /^\/job-listings(?:-|\/)/.test(url.pathname) ? url.origin + url.pathname : "";
    if (["secure.indeed.com", "auth.indeed.com", "accounts.indeed.com"].includes(host) ||
        !["/viewjob", "/m/viewjob", "/rc/clk", "/jobs", "/"].includes(url.pathname)) return "";
    const keys = url.searchParams.getAll("jk"), selected = url.searchParams.getAll("vjk");
    if (keys.length > 1 || selected.length > 1 ||
        (keys.length && selected.length && keys[0] !== selected[0])) return "";
    const id = keys[0] || selected[0] || "";
    return /^[a-f0-9]{16}$/i.test(id) ? url.origin + "/viewjob?jk=" + id.toLowerCase() : "";
  } catch (_) { return ""; }
}

async function awaitTabReady(tabId) {
  for (let attempt = 0; attempt < 20; attempt++) {
    try {
      const tab = await chrome.tabs.get(tabId);
      if (tab.status === "complete") return true;
    } catch (_) { return false; }
    await pause(500);
  }
  return false;
}

const normalizedHeader = value => String(value || "").split(/\r?\n/)[0].normalize("NFKC")
  .toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();

async function getDescription(job, portal) {
  let tab;
  try {
    tab = await chrome.tabs.create({url: job.url, active: false});
    if (!(await awaitTabReady(tab.id))) return {reason: "job_page_load_timeout"};
    for (let retry = 0; retry < 4; retry++) {
      await pause(retry === 0 ? 800 : 900);
      const current = await chrome.tabs.get(tab.id);
      if (safeJobUrl(current.url || "", portal) !== job.url) return {reason: "job_redirect_or_login"};
      const results = await chrome.scripting.executeScript({target: {tabId: tab.id},
        files: [portal === "naukri" ? "detail_capture.js" : "indeed_capture.js"]});
      const captured = results?.[0]?.result;
      const detail = portal === "naukri" ? captured :
        (captured?.portal === "indeed" && captured.page_kind === "detail" && captured.jobs?.length === 1 ? captured.jobs[0] : null);
      if (!detail || typeof detail.description !== "string" || detail.description.trim().length < 200) continue;
      if (safeJobUrl(detail.url, portal) !== job.url) return {reason: "extracted_job_identity_mismatch"};
      if (!normalizedHeader(detail.title) || !normalizedHeader(detail.company)) return {reason: "job_header_unverified"};
      if ((normalizedHeader(job.title) && normalizedHeader(job.title) !== normalizedHeader(detail.title)) ||
          (normalizedHeader(job.company) && normalizedHeader(job.company) !== normalizedHeader(detail.company)))
        return {reason: "job_header_identity_mismatch"};
      return {detail, reason: "verified_job_description"};
    }
    return {reason: "job_description_unavailable"};
  } catch (_) {
    return {reason: "job_page_unreadable"};
  } finally {
    if (tab && Number.isInteger(tab.id)) {
      try { await chrome.tabs.remove(tab.id); } catch (_) { /* Already closed by user. */ }
    }
  }
}

async function exportBatch(rawJobs, portal = "naukri") {
  if (!["naukri", "indeed"].includes(portal)) throw Error("unsupported_batch_portal");
  if (portal === "indeed" && !(await chrome.permissions.contains({origins: ["https://*.indeed.com/*"]})))
    throw Error("indeed_batch_permission_required");
  const candidates = [], seen = new Set();
  for (const record of Array.isArray(rawJobs) ? rawJobs.slice(0, BATCH_LIMIT) : []) {
    const url = safeJobUrl(record?.url, portal);
    if (!url || seen.has(url)) continue;
    seen.add(url);
    candidates.push({url, title: String(record.title || "").slice(0, 300),
      company: String(record.company || "").slice(0, 300), location: String(record.location || "").slice(0, 300)});
  }
  if (!candidates.length) throw Error("no_verified_posting_links_open_a_full_job_page");
  const deadline = Date.now() + BATCH_BUDGET_MS;
  const jobs = [];
  let fullDescriptions = 0, visited = 0;
  for (const job of candidates) {
    let captured = {reason: "batch_budget_exhausted"};
    if (Date.now() < deadline) { visited++; captured = await getDescription(job, portal); }
    const complete = Boolean(captured.detail);
    if (complete) fullDescriptions++;
    jobs.push({title: complete ? captured.detail.title.slice(0, 300) : job.title,
      company: complete ? captured.detail.company.slice(0, 300) : job.company,
      location: complete ? String(captured.detail.location || job.location).slice(0, 300) : job.location,
      url: job.url, description: complete ? captured.detail.description.slice(0, 25000) : "", capture_kind: "detail",
      jd_evidence: {status: captured.reason, job_identity_matched: complete, header_matched: complete}});
    if (Date.now() < deadline) await pause(700);
  }
  const payload = {schema_version: 1, portal, captured_at: new Date().toISOString(), page_kind: "detail", jobs};
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  await chrome.downloads.download({url: "data:application/json;charset=utf-8," + encodeURIComponent(JSON.stringify(payload, null, 2)),
    filename: portal + "-jobs-details-" + stamp + ".json", conflictAction: "uniquify", saveAs: false});
  return {status: "exported", visited, considered: jobs.length, full_jd: fullDescriptions,
    needing_full_jd: jobs.length - fullDescriptions};
}

chrome.runtime.onMessage.addListener((message, _sender, reply) => {
  if (!message || !["naukri_enrich_jds", "portal_enrich_jds"].includes(message.action)) return false;
  if (batchRunning) { reply({status: "blocked", reason: "batch_already_running"}); return false; }
  batchRunning = true;
  exportBatch(message.jobs, message.action === "naukri_enrich_jds" ? "naukri" : message.portal)
    .then(result => reply(result))
    .catch(error => reply({status: "error", reason: error?.message || "batch_failed"}))
    .finally(() => { batchRunning = false; });
  return true;
});
