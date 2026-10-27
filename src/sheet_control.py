"""Read-only control workbook import; no credentials or submission approval."""
from dataclasses import dataclass, field
from dataclasses import replace
from datetime import date,datetime
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zipfile import ZipFile, BadZipFile
from xml.etree import ElementTree as ET
import re

QUESTION_HEADERS=('Question Pattern','Category','Answer Source','Approved Answer','Auto Answer','Risk Level','Last Reviewed','Notes')
FACTS={'experience_years':'experience_years','notice_period_days':'notice_period_days',
       'current_ctc_inr':'current_ctc_inr','expected_ctc_inr':'expected_ctc_inr'}
PATTERN_FACTS={'notice period':'notice_period_days','total years of experience':'experience_years',
               'current ctc':'current_ctc_inr','expected ctc':'expected_ctc_inr'}


class ControlSheetError(ValueError):
    def __init__(self,reason,fields=()):
        super().__init__(reason)
        self.fields=tuple(fields)


@dataclass(frozen=True)
class ControlBundle:
    config: dict = field(repr=False)
    answers: tuple = field(repr=False)
    source_scope: str = 'exported_workbook_snapshot'

    def diagnostics(self):
        return dict(source_scope=self.source_scope,agent_enabled=self.config['agent_enabled'],
                    operating_mode=self.config['operating_mode'],question_rows=len(self.answers),
                    auto_answer_rows=sum(a['approved'] for a in self.answers),
                    review_required_rows=sum(not a['approved'] for a in self.answers),
                    submission_approval_required=True,submission_enabled=False)


def _text(value):
    return str(value).strip() if value is not None else ''


def _boolean(value):
    if value is True or _text(value).upper() in ('YES','TRUE'): return True
    if value is False or _text(value).upper() in ('NO','FALSE'): return False
    raise ControlSheetError('control_boolean_invalid')


def _number(value,field):
    try:
        parsed=Decimal(_text(value).replace(',',''))
    except InvalidOperation:
        raise ControlSheetError('control_quantity_invalid',(field,)) from None
    if not parsed.is_finite() or parsed<0:
        raise ControlSheetError('control_quantity_invalid',(field,))
    return parsed


def _normal(value):
    return ' '.join(re.sub(r'[^a-z0-9]+',' ',_text(value).lower()).split())


def _answer_quantity(value,key):
    text=_text(value).lower().replace(',','').replace('₹','').strip()
    text=re.sub(r'^(?:inr|rs\.?)\s*','',text)
    if key.endswith('_inr'):
        text=re.sub(r'\s+(?:per annum|per year|annually)$','',text)
    match=re.fullmatch(r'(\d+(?:\.\d+)?)(\+)?\s*(days?|years?|lpa|lakhs?|lacs?)?',text)
    if not match: return None
    unit=match.group(3) or ''
    if key.endswith('_inr') and unit not in ('','lpa','lakh','lakhs','lac','lacs'): return None
    if key=='notice_period_days' and (match.group(2) or unit not in ('','day','days')): return None
    if key=='experience_years' and unit not in ('','year','years'): return None
    number=Decimal(match.group(1))
    return number*100000 if unit in ('lpa','lakh','lakhs','lac','lacs') else number


def _date(value):
    try: return date.fromisoformat(_text(value)[:10])
    except ValueError: return None


def parse_control_rows(config_rows,question_rows,*,source_scope='exported_workbook_snapshot',today=None):
    if not isinstance(config_rows,list) or not isinstance(question_rows,list) or len(config_rows)>200 or len(question_rows)>1001:
        raise ControlSheetError('control_rows_invalid')
    if any(not isinstance(row,list) for row in config_rows+question_rows): raise ControlSheetError('control_rows_invalid')
    if len(config_rows)<3 or config_rows[2][:2]!=['Setting','Value'] or not question_rows or tuple(question_rows[0][:8])!=QUESTION_HEADERS:
        raise ControlSheetError('control_headers_unrecognized')
    config={}
    for row in config_rows[3:]:
        if not isinstance(row,list) or len(row)>8: raise ControlSheetError('control_rows_invalid')
        key=_text(row[0]) if row else ''
        if not key: continue
        if key in config: raise ControlSheetError('duplicate_control_setting',(key if key in FACTS else 'setting',))
        if re.search(r'password|credential|secret|token|login_email',key,re.I):
            raise ControlSheetError('credentials_must_use_private_provider')
        config[key]=row[1] if len(row)>1 else ''
    if not all(k in config for k in ('agent_enabled','operating_mode')):
        raise ControlSheetError('control_settings_missing')
    config['agent_enabled']=_boolean(config['agent_enabled'])
    config['operating_mode']=_text(config['operating_mode']).upper()
    if config['operating_mode'] not in ('VALIDATION','REVIEW','LIVE'):
        raise ControlSheetError('control_mode_invalid')
    for key in FACTS:
        if key in config and _text(config[key]):
            n=_number(config[key],key)
            if (key=='experience_years' and n>80) or (key=='notice_period_days' and (n>365 or n!=int(n))):
                raise ControlSheetError('control_quantity_invalid',(key,))
            config[key]=format(n.normalize(),'f')
    try: current=today or datetime.now(ZoneInfo(_text(config.get('timezone')) or 'Asia/Kolkata')).date()
    except ZoneInfoNotFoundError: raise ControlSheetError('control_timezone_invalid') from None
    answers=[]; seen=set()
    for index,row in enumerate(question_rows[1:],2):
        if not isinstance(row,list) or len(row)>8: raise ControlSheetError('control_rows_invalid')
        if not any(_text(x) for x in row): continue
        row=(row+['']*8)[:8]
        question=_normal(row[0]);answer=_text(row[3])
        if re.search(r'\b(?:password|otp|one time code|verification code|shared key|api key)\b',question):
            raise ControlSheetError('credentials_must_use_private_provider')
        if not question or len(question)>450 or len(answer)>2000:
            raise ControlSheetError('control_question_invalid')
        if question in seen: raise ControlSheetError('duplicate_control_question')
        seen.add(question)
        reviewed=_date(row[6]); source=_text(row[2]).lower(); risk=_text(row[5]).upper()
        auto=_boolean(row[4]) if row[4] not in (None,'') else False
        approved=(auto and bool(answer) and source in ('profile','cv + profile','user verified')
                  and risk in ('LOW','MEDIUM','HIGH') and reviewed is not None and 0<=(current-reviewed).days<=90)
        fact=PATTERN_FACTS.get(question)
        if approved and fact in config and _text(config[fact]):
            quantity=_answer_quantity(answer,fact)
            if quantity is None or quantity!=_number(config[fact],fact): approved=False
        answers.append(dict(question=question,answer=answer,approved=approved,row=index,
                            risk=risk,reviewed=reviewed.isoformat() if reviewed else ''))
    return ControlBundle(config,tuple(answers),source_scope)


def read_control_workbook(path):
    """Parse only Config/Question_Bank from an export; never edit or refresh it."""
    ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    try:
        with ZipFile(Path(path)) as archive:
            if sum(info.file_size for info in archive.infolist())>10_000_000:
                raise ControlSheetError('control_workbook_oversize')
            shared=[]
            if 'xl/sharedStrings.xml' in archive.namelist():
                shared=[''.join(node.itertext()) for node in ET.fromstring(archive.read('xl/sharedStrings.xml'))]
            relations={n.attrib['Id']:n.attrib['Target'] for n in ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
            tables={}
            for sheet in ET.fromstring(archive.read('xl/workbook.xml')).find('m:sheets',ns):
                name=sheet.attrib['name']
                if name not in ('Config','Question_Bank'): continue
                target=relations[sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']]
                target=target.lstrip('/') if target.startswith('/') else 'xl/'+target
                if not target.startswith('xl/worksheets/') or '..' in target.split('/'):
                    raise ControlSheetError('control_workbook_target_invalid')
                values={}
                for row in ET.fromstring(archive.read(target)).findall('m:sheetData/m:row',ns):
                    number=int(row.attrib['r'])
                    for cell in row.findall('m:c',ns):
                        column=re.match(r'([A-Z]+)',cell.attrib['r']).group(1)
                        if column not in 'ABCDEFGH' or len(column)!=1: continue
                        raw=cell.find('m:v',ns); inline=cell.find('m:is',ns)
                        value=raw.text if raw is not None else ''.join(inline.itertext()) if inline is not None else ''
                        if cell.find('m:f',ns) is not None:
                            raise ControlSheetError('control_formulas_require_live_review')
                        if cell.attrib.get('t')=='s': value=shared[int(value)]
                        if cell.attrib.get('t')=='b': value=value=='1'
                        if value not in (None,''): values.setdefault(number,{})[ord(column)-65]=value
                if max(values,default=0)>(200 if name=='Config' else 1001):
                    raise ControlSheetError('control_rows_invalid')
                tables[name]=[[values.get(r,{}).get(c,'') for c in range(8)] for r in range(1,max(values,default=0)+1)]
            return parse_control_rows(tables.get('Config',[]),tables.get('Question_Bank',[]))
    except ControlSheetError: raise
    except (OSError,BadZipFile,ET.ParseError,KeyError,ValueError,TypeError,AttributeError,IndexError):
        raise ControlSheetError('control_workbook_unreadable') from None


def _scope(question):
    text=_normal(question)
    if 'india' in text and any(t in text for t in ('authorization','authorised','authorized','eligible to work','legally work','legal right to work')): return 'india_authorization'
    if 'notice period' in text or ('days' in text and any(t in text for t in ('join','joining','start'))): return 'notice_period_days'
    if 'experience' in text and any(t in text for t in ('total','overall','professional')): return 'experience_years'
    if any(t in text for t in ('ctc','salary','compensation')):
        if 'current' in text: return 'current_ctc_inr'
        if 'expected' in text: return 'expected_ctc_inr'
    if 'relocat' in text: return 'relocation'
    if 'remote work' in text or 'work remotely' in text: return 'remote_work'
    if 'sponsorship' in text: return 'sponsorship'
    return ''


def merge_control_profile(profile,bundle):
    """Fill absent declared facts, reject conflicts, retain explicit unresolved rows."""
    merged=dict(profile); conflicts=[]
    for key in FACTS:
        value=bundle.config.get(key)
        if value in (None,''): continue
        previous=profile.get(key)
        if previous not in (None,''):
            try:
                existing=_number(_text(previous).rstrip('+'),key)
                current=_number(value,key)
                same=current>=existing if _text(previous).endswith('+') else current==existing
            except ControlSheetError: same=False
            if not same: conflicts.append(key)
        else: merged[key]=value
    if conflicts: raise ControlSheetError('control_profile_conflict',conflicts)
    bank={}; blocked=[]
    for item in bundle.answers:
        custom=profile.get('answers',{})
        previous=[v for k,v in custom.items() if _normal(k)==item['question'] and v not in (None,'')] if isinstance(custom,dict) else []
        if item['approved'] and any(_normal(v)!=_normal(item['answer']) for v in previous):
            raise ControlSheetError('control_answer_conflict',('question_row_'+str(item['row']),))
        alias={'notice period':'notice_period','current ctc':'current_ctc','expected ctc':'expected_ctc'}.get(item['question'])
        if item['approved'] and alias and profile.get(alias) not in (None,''):
            fact=PATTERN_FACTS[item['question']]
            current=_answer_quantity(item['answer'],fact); existing=_answer_quantity(profile[alias],fact)
            if current is None or existing is None or current!=existing:
                raise ControlSheetError('control_profile_conflict',(alias,))
        bank[item['question']]={'answer':item['answer'],'approved':item['approved']}
        if not item['approved']:
            scope=_scope(item['question'])
            if scope: blocked.append(scope)
    merged['_control_answer_bank']=bank
    merged['_control_blocked_scopes']=sorted(set(blocked))
    return merged


def resolve_control_answer(question,profile,options,required):
    """Return resolver kwargs, or None when the sheet has no exact decision."""
    from question_resolver import match_answer_to_option
    normalized=_normal(question)
    bank=profile.get('_control_answer_bank',{})
    item=bank.get(normalized) if isinstance(bank,dict) else None
    blocked=_scope(question) in profile.get('_control_blocked_scopes',()) if _scope(question) else False
    if item is None and not blocked: return None
    status='UNKNOWN_REQUIRED' if required else 'UNKNOWN_OPTIONAL'
    if blocked or not isinstance(item,dict) or item.get('approved') is not True:
        return dict(status=status,normalized_question=normalized,reason='control_answer_requires_review')
    answer=_text(item.get('answer'))
    selected=match_answer_to_option(answer,options)
    if not answer or (options and not selected):
        return dict(status=status,normalized_question=normalized,reason='control_answer_not_present_in_options')
    return dict(status='RESOLVED',answer=selected or answer,source='approved_control_question',normalized_question=normalized)


def requested_control(args,provider):
    path=getattr(args,'control_workbook','')
    live=getattr(args,'use_control_sheet',False)
    if path and live: raise ControlSheetError('choose_one_control_source')
    if not path and not live: return None
    return read_control_workbook(path) if path else provider.control_snapshot()


def load_requested_control(args,provider,public_profile,private_profile):
    bundle=requested_control(args,provider)
    if bundle is None: return public_profile,private_profile,None
    private=merge_control_profile(private_profile,bundle)
    updates={}
    for setting,attribute in (('preferred_roles','target_roles'),('preferred_locations','preferred_locations'),
                              ('excluded_keywords','blocked_title_terms'),('excluded_companies','excluded_companies')):
        text=bundle.config.get(setting)
        if text not in (None,''):
            if not isinstance(text,str) or len(text)>4000: raise ControlSheetError('control_filter_invalid')
            values=tuple(x.strip() for x in re.split(r'[,;\n|]',text) if x.strip())
            if len(values)>40: raise ControlSheetError('control_filter_invalid')
            if attribute in ('blocked_title_terms','excluded_companies'):
                values=tuple(dict.fromkeys(getattr(public_profile,attribute)+values))
            updates[attribute]=values
    if 'remote_allowed' in bundle.config: updates['remote_allowed']=_boolean(bundle.config['remote_allowed'])
    public=replace(public_profile,**updates)
    return public,private,bundle


def control_stop_reason(bundle,*,live_submission=False):
    if bundle is None: return ''
    if not bundle.config['agent_enabled']: return 'control_agent_paused'
    if live_submission:
        if bundle.source_scope!='live_readonly_sheet_bridge': return 'snapshot_cannot_authorize_live_run'
        if bundle.config['operating_mode']!='LIVE': return 'control_validation_mode'
        if any(not a['approved'] and a['risk']=='HIGH' for a in bundle.answers): return 'control_high_risk_answers_need_review'
    return ''


def restrictive_control_limits(bundle,threshold,daily_cap):
    score=_number(bundle.config.get('auto_apply_score',threshold),'auto_apply_score')
    cap=_number(bundle.config.get('daily_application_cap',daily_cap),'daily_application_cap')
    if score!=int(score) or not 75<=score<=100 or cap!=int(cap):
        raise ControlSheetError('control_limits_invalid')
    return max(threshold,int(score)),min(daily_cap,int(cap))


def main():
    import argparse,json
    from auth_bridge import AuthProvider,AuthProviderUnavailable
    parser=argparse.ArgumentParser(description='Validate control data without credentials, resume, browser or submissions.')
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--control-workbook',default='')
    group.add_argument('--use-control-sheet',action='store_true')
    parser.add_argument('--auth-config',default='data/auth_bridge.json')
    args=parser.parse_args()
    try:
        provider=AuthProvider(args.auth_config) if args.use_control_sheet else None
        bundle=requested_control(args,provider)
        print(json.dumps(dict(status='control_validated',**bundle.diagnostics()),sort_keys=True))
        return 0
    except (ControlSheetError,AuthProviderUnavailable) as exc:
        print(json.dumps(dict(status='control_requires_review',reason_code=str(exc),fields=list(getattr(exc,'fields',())))))
        return 2


if __name__=='__main__':
    raise SystemExit(main())
