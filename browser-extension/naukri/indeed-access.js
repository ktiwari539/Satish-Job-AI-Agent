/* Stable, user-invoked optional permission setup. No page/tab data is read. */
const accessOrigins = {origins: ["https://*.indeed.com/*"]};
const requestAccessButton = document.getElementById("request-access");
const accessStatus = document.getElementById("status");
const diagnosticText = document.getElementById("diagnostic");
let accessDiagnostic;
let accessOperation = 0;

function accessManifest() {
  return chrome.runtime.getManifest();
}

function accessPreflight() {
  const manifest = accessManifest();
  if (!manifest.optional_host_permissions?.includes(accessOrigins.origins[0]))
    return "manifest_missing_optional_host";
  if (typeof chrome.permissions?.request !== "function" || typeof chrome.permissions?.contains !== "function")
    return "permissions_api_unavailable";
  return "";
}

function accessErrorCode(error) {
  const message = String(error?.message || error || "");
  if (/context invalidated/i.test(message)) return "extension_context_invalidated";
  if (/user gesture/i.test(message)) return "user_gesture_required";
  if (/optional permissions|only permissions specified|not.*declared|not.*listed.*manifest/i.test(message)) return "manifest_missing_optional_host";
  if (/enterprise|administrator|admin policy|blocked.*policy|policy.*block/i.test(message)) return "browser_policy_blocked";
  return "permission_request_failed";
}

function sanitizedAccessError(error) {
  // Chrome errors are shown locally. Export no URLs/query tokens, email-like
  // strings or long identifiers even if an unexpected API error includes one.
  return String(error?.message || error || "").slice(0, 1000)
    .replace(/(?:https?|chrome-extension):\/\/\S+/gi, "[URL]")
    .replace(/[\w.+-]+@[\w.-]+/g, "[email]")
    .replace(/[A-Za-z0-9_-]{24,}/g, "[identifier]").slice(0, 400);
}

function showAccessResult(code, granted = false, error = null) {
  let version = "unavailable";
  try { version = String(accessManifest().version); } catch (_) { /* Invalidated context. */ }
  const messages = {
    access_enabled: "Indeed batch access is enabled. Return to your Indeed SEARCH tab, open the extension and choose Export full descriptions (up to 20). Keep that popup open.",
    access_not_granted: "Chrome has not granted Indeed batch access. You can choose Enable Indeed access and review Chrome's prompt, or export one full job using the steps below.",
    manifest_missing_optional_host: "The loaded extension manifest does not include Indeed batch access. Reload Satish Job Agent once at chrome://extensions, then reopen setup. Do not remove the extension or sign in again.",
    permissions_api_unavailable: "Chrome's extension permission API is unavailable here. Reload the extension once; if this persists, use current-job export below.",
    extension_context_invalidated: "This page belongs to an extension that was reloaded. Close this setup tab and reopen it from the extension.",
    user_gesture_required: "Chrome requires a direct button click. Click Enable Indeed access on THIS setup page. If Chrome still refuses, use current-job export below.",
    browser_policy_blocked: "Chrome reports a browser-policy restriction. This extension cannot override it. Use current-job export if allowed, or ask your browser administrator about the restriction.",
    permission_request_failed: "Chrome could not enable Indeed batch access. Its sanitized error is shown below. Use current-job export to continue; share the diagnostic if help is needed."
  };
  accessStatus.textContent = messages[code] || messages.permission_request_failed;
  accessDiagnostic = {schema_version: 1, mode: "ACCESS_DIAGNOSTIC", extension_version: version,
    code, access_granted: granted, checked_at: new Date().toISOString()};
  if (error) accessDiagnostic.browser_error = sanitizedAccessError(error);
  diagnosticText.textContent = JSON.stringify(accessDiagnostic, null, 2);
}

async function checkIndeedAccess() {
  const operation = ++accessOperation;
  try {
    const issue = accessPreflight();
    if (issue) { showAccessResult(issue); return; }
    const granted = await chrome.permissions.contains(accessOrigins);
    if (operation === accessOperation)
      showAccessResult(granted ? "access_enabled" : "access_not_granted", Boolean(granted));
  } catch (error) {
    if (operation === accessOperation) showAccessResult(accessErrorCode(error), false, error);
  }
}

requestAccessButton.addEventListener("click", async () => {
  ++accessOperation; // Ignore a slower, earlier check when the request finishes.
  requestAccessButton.disabled = true;
  document.getElementById("check-access").disabled = true;
  try {
    const issue = accessPreflight();
    if (issue) { showAccessResult(issue); return; }
    // First asynchronous API in the direct click handler; preserve user gesture.
    const granted = await chrome.permissions.request(accessOrigins);
    showAccessResult(granted ? "access_enabled" : "access_not_granted", Boolean(granted));
  } catch (error) { showAccessResult(accessErrorCode(error), false, error); }
  finally {
    requestAccessButton.disabled = false;
    document.getElementById("check-access").disabled = false;
  }
});
document.getElementById("check-access").addEventListener("click", checkIndeedAccess);
document.getElementById("save-diagnostic").addEventListener("click", () => {
  if (!accessDiagnostic) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(accessDiagnostic, null, 2)], {type: "application/json"}));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "indeed-access-diagnostic-" + new Date().toISOString().replace(/[:.]/g, "-") + ".json";
  document.body.appendChild(anchor); anchor.click(); anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
});
try { document.getElementById("version").textContent = "Loaded extension version " + accessManifest().version; }
catch (error) { showAccessResult(accessErrorCode(error), false, error); }
// Checking existing access never requests a permission or prompts the user.
checkIndeedAccess();
