"""Prepare the configured document at LinkedIn's resume step; never submits."""
from dataclasses import dataclass
from pathlib import Path

from application_forms import validate_resume_path
from radio_dom import RADIO_DOM_JS
from resume_evidence import RESUME_DOM_JS, _expected_names, inspect_resume_evidence
from resume_store import resolve_current_resume
from wizard_dom import WIZARD_DOM_JS


@dataclass(frozen=True)
class ResumePreparation:
    state: str
    action: str = ''
    reason: str = ''
    choice_keys: tuple[str, ...] = ()

    @property
    def may_advance(self):
        return not self.reason and self.state in (
            'matching_resume_selected', 'configured_file_pending_review')


_PICKER_JS = r"""({action,names=[]}) => {"""+WIZARD_DOM_JS+RADIO_DOM_JS+RESUME_DOM_JS+r"""
  // A progress/footer subtree may hold fields but omit the Resume title.
  // Prefer the whole bounded Resume scope; retain ordinary scope for diagnostics.
  const ordinary=agentWizardRoot();
  const root=ordinary&&(agentWizardRoot({requireResumeHeading:true})||ordinary);
  if(!root)return {picker:false,status:'no_picker',root_found:false};
  const heading_seen=agentResumePickerHeading(root);
  const candidates=agentResumeDocumentChoices(root,{includeAmbiguous:true});
  const choices=candidates.filter(choice=>choice.name);
  const inputs=[...root.querySelectorAll('input[type="file"]')].filter(el=>!el.disabled);
  const controls=[...root.querySelectorAll('button,[role="button"],input[type="button"],input[type="submit"]')].filter(agentWizardVisible);
  const uploadButtons=controls.filter(el=>{
    if(el.disabled||el.getAttribute('aria-disabled')==='true')return false;
    const labels=[el.innerText,el.textContent,el.getAttribute('aria-label'),el.value].map(agentWizardClean);
    if(labels.some(value=>/^upload(?: your| a)? (?:resume|cv)$/.test(value)))return true;
    // A bare Upload is usable only without a competing document purpose.
    return labels.includes('upload')&&
      !/\b(cover letter|portfolio|certificate|transcript)\b/.test(agentWizardClean(root.innerText));
  });
  const radio_count=root.querySelectorAll('input[type="radio"],[role="radio"]').length;
  const summary={root_found:true,heading_seen,document_radio_count:choices.length,
    radio_count,file_input_count:inputs.length,upload_button_count:uploadButtons.length,
    ambiguous_document_count:candidates.length-choices.length};
  if(controls.some(el=>agentWizardAction(el)==='submit'))return {...summary,picker:false,status:'review_read_only'};
  if(!heading_seen)return {...summary,picker:false,status:'no_resume_heading'};
  const picker=candidates.length>0||inputs.length>0||uploadButtons.length>0;
  const choice_keys=[...new Set(choices.flatMap(({members})=>members.flatMap(el=>[el.name,el.id].filter(Boolean))))];
  if(!picker||action==='inspect')return {...summary,picker,choice_keys,status:picker?'picker':'no_document_controls'};
  if(action==='select'){
    const expected=names.map(agentWizardClean);
    const matches=choices.filter(({name})=>expected.includes(name));
    if(matches.length!==1)return {picker,choice_keys,status:matches.length?'matching_choice_ambiguous':'matching_choice_absent'};
    const target=agentRadioClickTarget(matches[0].el);
    if(!target||!agentWizardVisible(target))return {picker,choice_keys,status:'matching_choice_not_clickable'};
    for(const node of document.querySelectorAll('[data-agent-resume-choice]'))node.removeAttribute('data-agent-resume-choice');
    target.setAttribute('data-agent-resume-choice','target');
    return {picker,choice_keys,status:'selection_prepared'};
  }
  if(action==='upload'){
    const label = el => agentWizardClean([el.getAttribute('aria-label'),
      ...[...el.labels||[]].map(n=>n.innerText),
      ...(el.getAttribute('aria-labelledby')||'').split(/\s+/).filter(Boolean)
        .map(id=>document.getElementById(id)?.textContent)].join(' '));
    const safe=inputs.filter(el=>!el.getAttribute('aria-disabled')?.match(/^true$/i)&&
      !/\b(cover letter|portfolio|certificate|transcript)\b/.test(label(el)));
    const labelled=safe.filter(el=>/\b(resume|cv)\b/.test(label(el)));
    const candidates=safe.length===1?safe:labelled;
    if(inputs.length===0&&uploadButtons.length===1){
      for(const node of document.querySelectorAll('[data-agent-resume-chooser]'))node.removeAttribute('data-agent-resume-chooser');
      uploadButtons[0].setAttribute('data-agent-resume-chooser','target');
      return {picker,choice_keys,status:'chooser_prepared'};
    }
    if(candidates.length!==1)return {picker,choice_keys,status:inputs.length||uploadButtons.length?'upload_control_ambiguous':'upload_control_absent'};
    for(const node of document.querySelectorAll('[data-agent-resume-upload]'))node.removeAttribute('data-agent-resume-upload');
    candidates[0].setAttribute('data-agent-resume-upload','target');
    return {picker,choice_keys,status:'upload_prepared'};
  }
  return {picker,choice_keys,status:'invalid_action'};
}"""


def _probe(page, action='inspect', names=()):
    try:
        result = page.evaluate(_PICKER_JS, dict(action=action, names=list(names)))
        return result if isinstance(result, dict) else {}
    except Exception:
        return {"status": "probe_failed"}


def is_resume_picker(page):
    return _probe(page).get('picker') is True


def resume_picker_diagnostics(page):
    """Only fixed categories/counts reach terminal reports, never field keys."""
    raw = _probe(page)
    statuses = {'no_picker','review_read_only','no_resume_heading',
                'picker','no_document_controls','probe_failed'}
    result = {'status': raw.get('status') if raw.get('status') in statuses else 'probe_invalid'}
    for key in ('root_found','heading_seen'):
        result[key] = raw.get(key) is True
    for key in ('document_radio_count','radio_count','file_input_count','upload_button_count','ambiguous_document_count'):
        value = raw.get(key)
        result[key] = min(max(value, 0), 100) if type(value) is int else 0
    return result


def _keys(result):
    values = result.get('choice_keys', ())
    if not isinstance(values, (list, tuple)):
        return ()
    return tuple(value for value in values if isinstance(value, str))


def prepare_resume_picker(page, resume_path):
    """Select one exact saved document or upload configured bytes once.

    A file input is only pending evidence. Final Review must independently
    verify the configured document before an application becomes ready.
    """
    target = Path(resume_path).expanduser()
    if not validate_resume_path(str(target))[0]:
        return ResumePreparation('resume_provenance_invalid', reason='configured_resume_unavailable')
    if (target.parent / 'manifest.json').exists():
        try:
            if resolve_current_resume(str(target.parent)) != target.resolve():
                raise ValueError('configured_resume_provenance_invalid')
        except (OSError, ValueError, TypeError, AttributeError):
            return ResumePreparation('resume_provenance_invalid', reason='configured_resume_provenance_invalid')
    info = _probe(page)
    if info.get('picker') is not True:
        return ResumePreparation('attachment_unverified', reason='resume_picker_changed')
    before = inspect_resume_evidence(page, str(target))
    if before == 'matching_resume_selected':
        return ResumePreparation(before, 'already_selected', choice_keys=_keys(info))
    names = _expected_names(str(target))
    prepared = _probe(page, 'select', names)
    selected = False
    if prepared.get('status') == 'selection_prepared':
        try:
            page.locator('[data-agent-resume-choice="target"]').click(timeout=2000)
        except Exception:
            return ResumePreparation(before, 'select_saved', 'resume_choice_click_failed', _keys(prepared))
        action = 'select_saved'
        selected = True
    else:
        upload = _probe(page, 'upload', names)
        if upload.get('status') not in ('upload_prepared', 'chooser_prepared'):
            reason = upload.get('status')
            if reason not in ('upload_control_ambiguous', 'upload_control_absent'):
                reason = 'resume_upload_control_unverified'
            return ResumePreparation(before, reason=reason, choice_keys=_keys(info))
        try:
            if upload.get('status') == 'chooser_prepared':
                # Register before the trusted click; the input may be created
                # lazily or remain detached from the document entirely.
                with page.expect_file_chooser(timeout=4000) as chooser:
                    page.locator('[data-agent-resume-chooser="target"]').click(timeout=2000)
                chooser.value.set_files(str(target), timeout=4000)
            else:
                page.locator('[data-agent-resume-upload="target"]').set_input_files(str(target))
        except Exception:
            return ResumePreparation(before, 'upload_configured', 'configured_resume_upload_failed', _keys(upload))
        action = 'upload_configured'
    state = before
    checks = 20 if action == 'upload_configured' else 10
    interval_ms = 250 if action == 'upload_configured' else 150
    for check in range(checks):
        state = inspect_resume_evidence(page, str(target))
        if state == 'matching_resume_selected':
            # React must retain the choice after its commit, not just a click.
            page.wait_for_timeout(150)
            retained = inspect_resume_evidence(page, str(target))
            if retained == state:
                return ResumePreparation(state, action, choice_keys=_keys(_probe(page)))
            state = retained
        if action == 'upload_configured' and not selected:
            choice = _probe(page, 'select', names)
            if choice.get('status') == 'selection_prepared':
                try:
                    page.locator('[data-agent-resume-choice="target"]').click(timeout=2000)
                except Exception:
                    return ResumePreparation(state, action, 'uploaded_resume_choice_click_failed', _keys(choice))
                selected = True
        if check + 1 < checks:
            page.wait_for_timeout(interval_ms)
    keys = _keys(_probe(page))
    if action == 'upload_configured' and state == 'file_input_selected_unconfirmed':
        return ResumePreparation('configured_file_pending_review', action, choice_keys=keys)
    return ResumePreparation(state, action, 'configured_resume_selection_unverified', keys)
