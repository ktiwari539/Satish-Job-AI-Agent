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
  const root=agentWizardRoot({requireDocument:true});
  if(!root)return {picker:false,status:'no_picker'};
  const controls=[...root.querySelectorAll('button,[role="button"],input[type="submit"]')].filter(agentWizardVisible);
  if(controls.some(el=>agentWizardAction(el)==='submit'))return {picker:false,status:'review_read_only'};
  if(!agentResumePickerHeading(root))return {picker:false,status:'no_resume_heading'};
  const choices=agentResumeDocumentChoices(root);
  const inputs=[...root.querySelectorAll('input[type="file"]')].filter(el=>!el.disabled);
  const picker=choices.length>0||inputs.length>0;
  const choice_keys=[...new Set(choices.flatMap(({members})=>members.flatMap(el=>[el.name,el.id].filter(Boolean))))];
  if(!picker||action==='inspect')return {picker,choice_keys,status:picker?'picker':'no_document_controls'};
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
    if(candidates.length!==1)return {picker,choice_keys,status:inputs.length?'upload_control_ambiguous':'upload_control_absent'};
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
        return {}


def is_resume_picker(page):
    return _probe(page).get('picker') is True


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
        if upload.get('status') != 'upload_prepared':
            reason = upload.get('status')
            if reason not in ('upload_control_ambiguous', 'upload_control_absent'):
                reason = 'resume_upload_control_unverified'
            return ResumePreparation(before, reason=reason, choice_keys=_keys(info))
        try:
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
