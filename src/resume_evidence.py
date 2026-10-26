"""Privacy-preserving read-only evidence for the selected application resume.

Never logs a filename, DOM text, local path, or resume contents. A selected
local file input is not proof that LinkedIn accepted the attachment.
"""
import json
from pathlib import Path
from resume_store import resolve_current_resume


def _expected_names(resume_path: str) -> list[str]:
    target = Path(resume_path).expanduser()
    names = [target.name]
    manifest = target.parent / "manifest.json"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        if payload.get("current_file") == target.name:
            # An alias without verified local provenance could certify an
            # unrelated saved document. The vault resolver checks its digest.
            if resolve_current_resume(str(target.parent)) != target.resolve():
                raise ValueError("resume_alias_provenance_invalid")
            original = str(payload.get("original_name") or "").strip()
            if original:
                names.append(Path(original).name)
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return list(dict.fromkeys(name.lower().strip() for name in names if name))


_RESUME_PROBE = r"""({ names, external }) => {
  const canonical = v => String(v || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const expected = names.map(canonical).filter(Boolean);
  const visible = el => {
    if (!el || !el.isConnected) return false;
    const s = getComputedStyle(el), r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' &&
           r.width > 0 && r.height > 0;
  };
  const roots = Array.from(document.querySelectorAll(
    '.jobs-easy-apply-modal, .artdeco-modal, [role="dialog"]'
  )).filter(visible);
  // An inline application wizard can have no dialog. Use a bounded,
  // application-related container, not arbitrary saved-profile text.
  const inline = Array.from(document.querySelectorAll(
    '.jobs-easy-apply-content, .jobs-easy-apply-form-section__grouping, ' +
    '[class*="jobs-easy-apply"]'
  )).filter(visible);
  // Some LinkedIn Easy Apply pages are inline and have no known
  // jobs-easy-apply classes. Limit fallback to a visible N/M pages counter,
  // bounded ancestor, real editable fields, and a Next/Review control.
  // This is NOT permission to consider any filename in document.body proof.
  const pageCounters = Array.from(document.querySelectorAll(
    'span, p, small, div'
  )).filter(visible).filter(el => {
    const t = canonical(el.innerText || el.textContent);
    return /^\d+\s*\/\s*\d+\s*pages?$/.test(t) &&
      !Array.from(el.children || []).some(child =>
        /^\d+\s*\/\s*\d+\s*pages?$/.test(
          canonical(child.innerText || child.textContent)));
  });
  let inlineWizard = null;
  for (const marker of pageCounters.slice(0, 12)) {
    let candidate = marker.parentElement;
    for (let depth = 0; candidate && depth < 10;
         depth++, candidate = candidate.parentElement) {
      if (!visible(candidate)) continue;
      const text = canonical(candidate.innerText || candidate.textContent);
      if (text.length > 9000) break;
      const hasNext = Array.from(candidate.querySelectorAll(
        'button, [role="button"]'
      )).some(button => visible(button) &&
        /^(next|review|back|continue|submit application|submit|send application)$/i.test(
          canonical(button.innerText || button.textContent ||
                    button.getAttribute('aria-label'))));
      if (hasNext) {
        if (!inlineWizard ||
            text.length < canonical(inlineWizard.innerText).length)
          inlineWizard = candidate;
        break;
      }
    }
  }
  const scoped = roots.length ? roots : inline;
  const containers = Array.from(new Set([
    ...scoped, ...(inlineWizard ? [inlineWizard] : [])
  ]));
  if (external) {
    const forms = [...document.querySelectorAll('form')].filter(visible);
    if (forms.length === 1) containers.push(forms[0]);
  }
  // Inspect individual visible filename nodes, not substring matches in a
  // whole card containing multiple saved resumes. Keep spaces in filenames.
  const fileNames = box => {
    const found = new Set();
    const take = value => {
      const t = canonical(value);
      const m = t.match(/^(.+\.(?:pdf|docx?))(?=\s*(?:$|uploaded\b|last used\b|selected\b|\d+(?:\.\d+)?\s*(?:kb|mb)\b))/i);
      if (m) found.add(m[1].trim());
    };
    for (const el of [box, ...box.querySelectorAll('*')].slice(0, 150)) {
      if (!visible(el)) continue;
      for (const node of el.childNodes) if (node.nodeType === Node.TEXT_NODE) take(node.textContent);
      for (const attr of ['title','aria-label','download']) take(el.getAttribute(attr));
    }
    return [...found];
  };
  const record = box => {
    const files = fileNames(box);
    if (files.some(name => expected.includes(name))) savedMatch = true;
    if (files.some(name => !expected.includes(name))) savedMismatch = true;
    return files.length > 0;
  };
  let localFileSelected = false, savedMatch = false, savedMismatch = false;
  for (const root of containers) {
    for (const input of root.querySelectorAll('input[type="file"]')) {
      for (const file of Array.from(input.files || [])) {
        if (expected.includes(canonical(file.name))) localFileSelected = true;
      }
    }
    const selected = root.querySelectorAll(
      'input[type="radio"]:checked, [role="radio"][aria-checked="true"], ' +
      '[aria-selected="true"]'
    );
    for (const node of selected) {
      let matchedBox = false;
      if (node.id) {
        const label = root.querySelector('label[for="' + CSS.escape(node.id) + '"]');
        if (label && visible(label)) matchedBox = record(label);
      }
      const box = node.closest('label, [class*="resume"], [class*="document"]');
      if (!matchedBox && box && visible(box) && root.contains(box) &&
          box.querySelectorAll('input[type="radio"],[role="radio"]').length <= 1)
        matchedBox = record(box);
      // LinkedIn's inline saved-resume cards may have a native radio with
      // no wrapping label/resume class. Inspect only three bounded ancestors
      // inside the verified application wizard, never the whole page.
      if (!matchedBox) {
        let parent = node.parentElement;
        for (let depth = 0; parent && depth < 3 && root.contains(parent);
             depth++, parent = parent.parentElement) {
          if (!visible(parent)) continue;
          const text = canonical(parent.innerText || parent.textContent);
          if (text.length > 350) break;
          if (parent.querySelectorAll('input[type="radio"],[role="radio"]').length > 1) break;
          if (/\.(pdf|docx?)\b/i.test(text)) {
            record(parent);
            break;
          }
        }
      }
    }
    // Final Review often renders a document link/card with no selection
    // radio. Require a bounded Resume section inside this application.
    for (const section of root.querySelectorAll(
      '[class*="resume"],[data-test*="resume"],section,fieldset'
    )) {
      if (!visible(section) || canonical(section.innerText).length > 600) continue;
      if (section.querySelector('input[type="radio"],[role="radio"],input[type="file"]')) continue;
      const heading = section.querySelector('h2,h3,h4,legend,[role="heading"]');
      if (!heading || !/^(resume|cv|resume attachment)$/i.test(canonical(heading.innerText))) continue;
      if (!section.querySelector('a,[class*="document"],[data-test*="resume"]')) continue;
      record(section);
    }
  }
  return {savedMatch, savedMismatch, localFileSelected};
}"""


def inspect_resume_evidence(page, resume_path: str, *, external=False) -> str:
    """Return a safe categorical state, never the actual file name."""
    if not resume_path:
        return "no_resume_configured"
    target = Path(resume_path).expanduser()
    if (target.parent / "manifest.json").exists():
        try:
            if resolve_current_resume(str(target.parent)) != target.resolve():
                return "resume_provenance_invalid"
        except (OSError, ValueError, TypeError, AttributeError):
            return "resume_provenance_invalid"
    try:
        raw = page.evaluate(_RESUME_PROBE, {"names": _expected_names(resume_path), "external": external})
    except Exception:
        return "attachment_unverified"
    if not isinstance(raw, dict):
        return "attachment_unverified"
    if raw.get("savedMismatch") is True:
        return "different_resume_selected"
    if raw.get("savedMatch") is True:
        return "matching_resume_selected"
    if raw.get("localFileSelected") is True:
        return "file_input_selected_unconfirmed"
    return "attachment_unverified"
