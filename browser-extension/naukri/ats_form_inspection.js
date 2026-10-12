/* Explicit user-invoked inspection on an external employer ATS page.
 * NO form values, cookies, tokens, file names, account information or clicks.
 * This is diagnostic only, never submission evidence or an auto-fill action.
 */
(() => {
  const result = {
    schema_version: 1,
    portal: "external_ats",
    mode: "READ_ONLY_FORM_INSPECTION",
    captured_at: new Date().toISOString(),
    status: "unsupported_page",
    site_origin: "",
    fields: [],
    action_controls: [],
    frame_count: 0,
    captcha_present: false,
    otp_present: false,
    login_required: false,
    submitted: 0,
    confirmed: 0
  };
  let url;
  try { url = new URL(location.href); } catch (_) { return result; }
  const host = url.hostname.toLowerCase();
  const isNaukri = host === "naukri.com" || host.endsWith(".naukri.com");
  const prohibited = isNaukri || host === "accounts.google.com" ||
    host === "google.com" || host.endsWith(".google.com") ||
    host === "gmail.com" || host.endsWith(".gmail.com") ||
    /(?:^|\.)(?:paypal|stripe|bank|facebook|instagram|linkedin)\.com$/.test(host);
  const likelyHiring = /(?:career|jobs?|apply|application|position|vacanc|recruit|hiring|opportunit)/i.test(
    host + url.pathname
  ) || /(?:greenhouse\.io|lever\.co|ashbyhq\.com|workdayjobs\.com|smartrecruiters\.com|myworkdayjobs\.com)$/i.test(host);
  if (url.protocol !== "https:" || prohibited || !likelyHiring ||
      url.username || url.password) return result;

  result.site_origin = url.origin;
  result.status = "read_only_inspection";
  const clip = (s, max = 110) => String(s || "").replace(/\s+/g, " ").trim().slice(0, max);
  const safeLabel = (text) => clip(text)
    .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, "[email]")
    .replace(/https?:\/\/\S+/gi, "[url]")
    .replace(/(?:\+\d[\d\s().-]{8,}\d)/g, "[phone]")
    .replace(/(?:\d[\d\s().-]{9,}\d)/g, "[number]");

  const classify = (label, type) => {
    const text = label.toLowerCase();
    if (type === "file" || /\b(resume|cv|curriculum vitae)\b/.test(text)) return "resume";
    if (/\b(e-?mail)\b/.test(text)) return "email";
    if (/\b(phone|mobile|telephone)\b/.test(text)) return "phone";
    if (/\b(first|last|full|legal) name\b/.test(text)) return "name";
    if (/\b(linkedin|portfolio|website)\b/.test(text)) return "profile_link";
    if (/\b(notice period|available to start|joining date)\b/.test(text)) return "availability";
    if (/\b(current salary|expected salary|compensation|ctc)\b/.test(text)) return "compensation";
    if (/\b(work authorization|legally authorized|sponsorship|visa)\b/.test(text)) return "authorization";
    if (/\b(years? of experience|work experience)\b/.test(text)) return "experience";
    if (/\b(gender|race|ethnicity|disability|veteran)\b/.test(text)) return "sensitive_optional";
    if (/\b(agree|consent|privacy policy|terms and conditions)\b/.test(text)) return "consent";
    return "other_question";
  };
  const allowedTypes = new Set([
    "text", "email", "tel", "number", "file", "checkbox", "radio", "date",
    "select", "textarea", "url", "password"
  ]);
  for (const el of Array.from(document.querySelectorAll("input,textarea,select")).slice(0, 90)) {
    try {
      if (!el.getClientRects().length) continue;
      const tag = el.tagName.toLowerCase();
      const type = tag === "input" ? String(el.type || "text").toLowerCase() : tag;
      if (!allowedTypes.has(type)) continue;
      // Label *names* only. NEVER inspect .value, checked state, selected
      // option, innerHTML, session state or uploaded file names.
      const explicit = Array.from(el.labels || []).map(label => label.textContent || "").join(" ");
      const label = safeLabel(explicit || el.getAttribute("aria-label") ||
        el.getAttribute("placeholder") || "");
      result.fields.push({
        type,
        required: el.required === true || el.getAttribute("aria-required") === "true",
        category: classify(label, type),
        label
      });
    } catch (_) { /* Unreadable field is skipped, never guessed. */ }
    if (result.fields.length >= 50) break;
  }

  const actions = new Set();
  for (const item of Array.from(document.querySelectorAll(
    "button, input[type='submit'], [role='button']"
  )).slice(0, 100)) {
    try {
      if (!item.getClientRects().length) continue;
      const text = clip(item.textContent || item.getAttribute("aria-label"), 80).toLowerCase();
      if (/submit (?:my |the )?application|send application|complete application/.test(text)) actions.add("submit_application");
      else if (/\bapply now|\bapply for|\bapply\b/.test(text)) actions.add("apply");
      else if (/\bnext\b|\bcontinue\b/.test(text)) actions.add("continue");
      else if (/\breview\b/.test(text)) actions.add("review");
      else if (/\blog ?in\b|\bsign ?in\b/.test(text)) actions.add("sign_in");
    } catch (_) { /* Ignore unsupported element. */ }
  }
  result.action_controls = Array.from(actions).sort();
  result.frame_count = Math.min(document.querySelectorAll("iframe").length, 100);
  const visibleText = (document.body?.innerText || "").slice(0, 90000).toLowerCase();
  result.captcha_present = /\b(captcha|verify you are human|i'm not a robot)\b/.test(visibleText);
  result.otp_present = /\b(enter otp|one.time password|authentication code)\b/.test(visibleText);
  result.login_required = /\b(sign in to apply|log in to continue|login to apply)\b/.test(visibleText);
  return result;
})();
