/* Non-interactive application UI inspector. No form values or personal data.
 * This function is invoked by the user on an open Naukri job page.
 */
(() => {
  const result = {
    schema_version: 2,
    portal: "naukri",
    mode: "READ_ONLY_INSPECTION",
    captured_at: new Date().toISOString(),
    job_url: "",
    application_controls: [],
    application_targets: [],
    required_field_types: [],
    visible_input_types: [],
    frame_count: 0,
    captcha_present: false,
    otp_present: false,
    account_login_present: false
  };
  let url;
  try { url = new URL(location.href); } catch (_) { return result; }
  if (url.protocol !== "https:" ||
      !(url.hostname === "naukri.com" || url.hostname.endsWith(".naukri.com")) ||
      !url.pathname.includes("job-listings")) return result;
  result.job_url = url.origin + url.pathname;

  const classify = (node) => {
    const text = (node.innerText || node.textContent || node.value || "")
      .replace(/\s+/g, " ").trim().toLowerCase().slice(0, 100);
    if (/\b(already applied|application sent|applied successfully)\b/.test(text)) return "already_applied";
    if (/\b(apply on company|apply on employer|apply on website)\b/.test(text)) return "external_apply";
    if (/\b(easy apply|apply now|apply for|apply)\b/.test(text)) return "apply";
    if (/\b(submit application|submit)\b/.test(text)) return "submit";
    if (/\b(next|continue|review application)\b/.test(text)) return "next_or_review";
    if (/\b(sign in|log in|login)\b/.test(text)) return "login";
    return "";
  };
  const controls = new Set();
  for (const node of Array.from(document.querySelectorAll(
    "button, a, [role='button'], input[type='submit']"
  )).slice(0, 300)) {
    if (!(node instanceof Element)) continue;
    let visible = false;
    try { visible = !!(node.getClientRects().length); } catch (_) { /* hidden */ }
    if (!visible) continue;
    const category = classify(node);
    if (!category) continue;
    controls.add(category);
    if (!["external_apply", "apply", "already_applied"].includes(category)) continue;
    let actionKind = "interactive_control";
    let targetOrigin = "";
    try {
      // Inspect link structure only: never click the control or access cookies.
      const link = node.closest?.("a[href]") ||
        (node.matches?.("a[href]") ? node : null);
      const rawLink = link && link.getAttribute("href");
      if (rawLink) {
        const destination = new URL(rawLink, location.href);
        if (destination.protocol === "https:" && !destination.username &&
            !destination.password) {
          targetOrigin = destination.origin; // no path, tokens, or query
          actionKind = destination.hostname.endsWith(".naukri.com") ||
            destination.hostname === "naukri.com" ? "naukri_link" : "external_link";
        }
      }
    } catch (_) { /* Never guess unknown button actions. */ }
    if (result.application_targets.length < 8) {
      const entry = {control: category, action_kind: actionKind};
      if (targetOrigin) entry.target_origin = targetOrigin;
      result.application_targets.push(entry);
    }
  }
  result.application_controls = Array.from(controls).sort();

  const allowedTypes = new Set([
    "email", "tel", "file", "text", "number", "password", "checkbox",
    "radio", "date", "textarea", "select", "url"
  ]);
  const types = new Set();
  const requiredTypes = new Set();
  for (const el of Array.from(document.querySelectorAll("input, textarea, select")).slice(0, 100)) {
    const type = el.tagName.toLowerCase() === "input" ?
      String(el.type || "text").toLowerCase() : el.tagName.toLowerCase();
    if (!allowedTypes.has(type)) continue;
    types.add(type);
    if (el.required || el.getAttribute("aria-required") === "true") requiredTypes.add(type);
  }
  result.visible_input_types = Array.from(types).sort();
  result.required_field_types = Array.from(requiredTypes).sort();
  result.frame_count = Math.min(document.querySelectorAll("iframe").length, 100);
  const text = (document.body?.innerText || "").slice(0, 120000).toLowerCase();
  result.captcha_present = /\b(captcha|i'm not a robot|verify you are human)\b/.test(text);
  result.otp_present = /\b(enter otp|one.time password|verification code)\b/.test(text);
  result.account_login_present = /\b(log in to apply|sign in to apply|login to apply)\b/.test(text);
  return result;
})();
