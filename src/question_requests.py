"""Private, local review of actual unanswered prompts. Never submits."""
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile

from answer_learning import _store_private_answer_bank
from application_forms import resolve_profile_key
from browser_form_runtime import inspect_page_fields
from question_resolver import normalize_question, resolve_application_answer, match_answer_to_option
from screening_groups import inspect_screening_groups
from answer_facts import fact_question, quantity, format_field_answer


DEFAULT_PATH='data/questions/pending.json'
_SECRET=re.compile(r'\b(?:password|passcode|otp|one time|verification code|security code|credential|token|api key|shared key)\b',re.I)


def _read(path):
    target=Path(path)
    if not target.exists():return []
    if target.stat().st_size>1000000:raise ValueError('question_file_too_large')
    data=json.loads(target.read_text())
    if not isinstance(data,dict) or not isinstance(data.get('questions'),list):raise ValueError('question_file_invalid')
    return data['questions'][:200]


def _write(path, rows):
    target=Path(path);target.parent.mkdir(parents=True,exist_ok=True)
    descriptor,name=tempfile.mkstemp(prefix='.questions-',dir=target.parent)
    try:
        with os.fdopen(descriptor,'w') as output:
            json.dump(dict(schema_version=1,scope='private_local_questions_no_answers',questions=rows[-200:]),output,indent=2)
            output.write('\n')
        os.replace(name,target)
    finally:
        if os.path.exists(name):os.unlink(name)


def record_pending_questions(page, job, profile, unknown, missing=(), *, path=DEFAULT_PATH, rejected=False):
    """Keep actual prompts locally so missing facts can be reviewed once.

    No entered values, answer contents, page HTML, screenshots or credentials.
    Unlike shareable blocker counters, this mode-600 file contains questions
    and must remain private. Never include it in CI artifacts or Git.
    """
    requested={normalize_question(q) for q in unknown}
    fields=[asdict(f) for f in inspect_page_fields(page)]
    rejected_questions=set()
    if rejected:
        try:
            keys=page.evaluate(r"""() => {
              const visible=el=>{const r=el.getBoundingClientRect();return r.width>0&&r.height>0&&getComputedStyle(el).visibility!=='hidden'};
              const root=[...document.querySelectorAll('.jobs-easy-apply-modal,.artdeco-modal,[role="dialog"]')].find(visible)||document;
              return [...root.querySelectorAll('input,textarea,select')].filter(el=>visible(el)&&!el.disabled&&
                (el.getAttribute('aria-invalid')==='true'||(el.validity&&!el.validity.valid)))
                .slice(0,40).map(el=>el.name||el.id||'');
            }""")
        except Exception:keys=[]
        if isinstance(keys,list):
            rejected_questions={normalize_question(f['label']) for f in fields if f.get('key') in keys}
            requested.update(rejected_questions)
    fields.extend(dict(label=g['question'],field_type='radio',required=g['required'],options=g['options'])
                  for g in inspect_screening_groups(page))
    pending={}
    for field in fields:
        question=str(field.get('label') or '').strip();normalized=normalize_question(question)
        if normalized not in requested and resolve_profile_key(question) not in missing:continue
        kind=str(field.get('field_type') or '')
        meaningful=(len(question)>=6 or resolve_profile_key(question) is not None or fact_question(question) is not None)
        if not meaningful or len(question)>450 or kind in ('file','password','hidden') or _SECRET.search(question):continue
        if normalized in ('yes','no','required','unverified screening question') or re.fullmatch(r'field \d+',normalized):continue
        if re.search(r'@|\.(?:docx?|pdf|rtf)\b',question,re.I):continue
        options=[str(o) for o in field.get('options',()) if isinstance(o,str) and 0<len(o)<=200 and not _SECRET.search(o) and '@' not in o]
        resolution=resolve_application_answer(question,profile,options=tuple(options),required=True)
        identifier=sha256((job.source+':'+job.external_id+':'+normalized).encode()).hexdigest()[:24]
        item=dict(id=identifier,source=job.source,job_id=job.external_id,question=question,
                  field_type=kind,options=options[:30],status='needs_review',
                  reason=resolution.reason or ('control_answer_format_requires_review'
                      if resolution.source=='approved_control_question' else 'field_format_requires_review'))
        if normalized in rejected_questions:
            item['reason']='control_value_rejected' if resolution.source=='approved_control_question' else 'verified_value_rejected'
        previous=pending.get(identifier)
        if previous is None or len(item['options'])>len(previous['options']):pending[identifier]=item
    if not pending:return ''
    rows=[r for r in _read(path) if isinstance(r,dict) and r.get('id') not in pending]
    _write(path,rows+list(pending.values()))
    return str(path)


def review_pending_questions(profile_path, *, path=DEFAULT_PATH):
    """Local terminal editor: answers go only to the existing private profile."""
    target=Path(profile_path)
    if target.stat().st_size>1000000:raise ValueError('private_profile_too_large')
    profile=json.loads(target.read_text())
    if not isinstance(profile,dict):raise ValueError('private_profile_must_be_mapping')
    if any(str(key).startswith('_control_') for key in profile):raise ValueError('private_profile_contains_transient_controls')
    bank=profile.setdefault('answers',{})
    if not isinstance(bank,dict):raise ValueError('private_answers_must_be_mapping')
    job_banks=profile.setdefault('job_answers',{})
    if not isinstance(job_banks,dict):raise ValueError('private_job_answers_must_be_mapping')
    rows=_read(path);saved=skipped=0;seen=set()
    for row in rows:
        if not isinstance(row,dict) or row.get('status')!='needs_review':continue
        question=str(row.get('question') or '');normalized=normalize_question(question)
        shared=fact_question(question) is not None or resolve_profile_key(question) is not None
        scope='shared_profile_fact' if shared else str(row.get('source',''))+':'+str(row.get('job_id',''))
        if not (len(question)>=6 or shared) or len(question)>450 or _SECRET.search(question) or (scope,normalized) in seen:continue
        seen.add((scope,normalized))
        if str(row.get('reason') or '').startswith('control_'):
            print('This question is held by the control Sheet; review that decision there.',flush=True)
            skipped+=1;continue
        options=row.get('options',[])
        if not isinstance(options,list) or any(not isinstance(o,str) or len(o)>200 for o in options):continue
        print('\nQuestion: '+question,flush=True)
        print('Scope: '+scope,flush=True)
        if row.get('reason')=='verified_value_rejected':
            print('The portal rejected this value. Correct its format or an actual factual mistake; keep the answer truthful.',flush=True)
        if options:print('Options: '+' / '.join(options),flush=True)
        destination=bank if shared else job_banks.get(scope,{})
        if not isinstance(destination,dict):raise ValueError('private_job_answers_must_be_mapping')
        if any(normalize_question(k)==normalized for k in destination):
            print('A saved answer exists. Type a replacement to edit it.',flush=True)
        try:answer=input('Truthful answer (Enter=skip, :stop=end): ').strip()
        except (EOFError,KeyboardInterrupt):break
        if answer==':stop':break
        if not answer or len(answer)>2000:skipped+=1;continue
        if options:
            answer=match_answer_to_option(answer,options)
            if not answer:
                print('No unique matching option. Answer not saved.',flush=True)
                skipped+=1;continue
        updated={k:v for k,v in destination.items() if normalize_question(k)!=normalized}
        updated[question]=answer
        candidate={**profile,'answers':updated} if shared else {**profile,'job_answers':{**job_banks,scope:updated}}
        if shared:
            request=fact_question(question)
            key=request.key if request else resolve_profile_key(question)
            canonical=answer
            if key.endswith('_inr') or key.endswith('_years') or key=='notice_period_days':
                unit=(request.unit if request else '') or ('days' if key=='notice_period_days' else 'years' if key.endswith('_years') else '')
                number=quantity(answer,key,source_unit=unit)
                if number is None:
                    print('Use an explicit, exact quantity and unit. Answer not saved.',flush=True)
                    skipped+=1;continue
                canonical=format(number.normalize(),'f')
                alias=key.removesuffix('_inr') if key.endswith('_inr') else 'notice_period' if key=='notice_period_days' else ''
                if alias and alias in profile:candidate[alias]=('INR '+canonical) if key.endswith('_inr') else canonical+' days'
            if key=='date_of_birth':
                canonical=format_field_answer(question,answer,'date')
                if canonical is None:
                    print('Use an unambiguous date, such as YYYY-MM-DD. Answer not saved.',flush=True)
                    skipped+=1;continue
            candidate[key]=canonical
        _store_private_answer_bank(profile_path,candidate)
        profile=candidate;bank=profile['answers'];job_banks=profile['job_answers'];saved+=1
        for item in rows:
            same_job=isinstance(item,dict) and str(item.get('source',''))+':'+str(item.get('job_id',''))==scope
            if isinstance(item,dict) and normalize_question(item.get('question',''))==normalized and (shared or same_job):
                item['status']='saved_for_next_run'
        _write(path,rows)
        print('Saved privately. The next preparation run will verify the answer on the form.',flush=True)
    return dict(answers_saved=saved,questions_skipped=skipped,submission_enabled=False)
