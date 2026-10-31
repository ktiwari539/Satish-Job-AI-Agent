"""Deterministic wording/unit mappings; never create applicant facts."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from datetime import date, datetime
import re


def normal(value):
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', str(value or '').lower()).split())


@dataclass(frozen=True)
class FactQuestion:
    key: str
    unit: str = ''


def fact_question(question):
    question=str(question or '')
    q = normal(question)
    q = re.sub(r' (?:required|mandatory)$', '', q)
    q = re.sub(r'^(?:(?:what is|what s|what are|please enter|please specify|please provide|please state|enter|specify|provide|state) )+(?:your )?', '', q)
    q = re.sub(r'^your ', '', q)
    salary = re.fullmatch(r'(current|present|existing|expected|desired) (?:annual |yearly )?(?:ctc|salary|compensation)(?: (?:in |per )?(?:inr|rs|rupees|lpa|lakhs?|lacs?|annum|year|annually))*', q)
    if salary or re.fullmatch(r'salary expectations?(?: in (?:inr|lpa))?', q):
        key = 'current_ctc_inr' if salary and salary[1] in ('current','present','existing') else 'expected_ctc_inr'
        unit = 'lpa' if re.search(r'\b(?:lpa|lakhs?|lacs?)\b', q) else 'inr' if re.search(r'\b(?:inr|rs|rupees)\b', q) or '₹' in question else ''
        return FactQuestion(key, unit)
    if re.fullmatch(r'notice period(?: in days| days)?|how many days is your notice period|(?:how many|number of) days (?:do you need to|until you can|to) (?:join|start)(?: us)?', q):
        return FactQuestion('notice_period_days', 'days' if 'days' in q else '')
    scope = r'(customer success(?: management)?|client success|people management|team management)'
    if re.fullmatch(scope+r' experience(?: in years| years)?', q) or re.fullmatch(r'(?:how many )?years of (?:work )?experience (?:do you have )?(?:in|with) '+scope, q):
        return FactQuestion('customer_success_years' if re.search(r'customer|client',q) else 'people_management_years','years')
    if re.fullmatch(r'(?:total|overall|professional)(?: years of)? experience(?: in years| years)?|total years of experience|how many years of (?:total |overall |professional )?experience do you have', q):
        return FactQuestion('experience_years','years')
    aliases = {
        'full name':'full_name','first name':'first_name','last name':'last_name',
        'email':'email','email address':'email','phone number':'phone','mobile number':'phone',
        'mobile phone number':'phone','current city':'location','current location':'location',
        'current employer':'current_company','current company':'current_company',
        'current designation':'current_title','current job title':'current_title','current role':'current_title',
        'linkedin profile url':'linkedin','linkedin profile link':'linkedin',
        'highest qualification':'education_level','highest educational qualification':'education_level',
        'university name':'university','college name':'university',
        'date of birth':'date_of_birth','dob':'date_of_birth','birth date':'date_of_birth',
    }
    return FactQuestion(aliases[q]) if q in aliases else None


def quantity(value, key, *, source_unit=''):
    """Return exact base units, or unknown; lower bounds are not exact values."""
    text = str(value).strip().lower().replace(',', '')
    if re.search(r'\b(?:usd|eur|gbp|monthly|month)\b',text):return None
    inr = bool(re.search(r'\b(?:inr|rs|rupees)\b',text) or '₹' in text)
    text = re.sub(r'^(?:inr|rs\.?|₹)\s*','',text)
    text = re.sub(r'\s+(?:per annum|per year|annually)$','',text)
    match = re.fullmatch(r'(\d+(?:\.\d+)?)\s*(lpa|lakhs?|lacs?|days?|years?)?',text)
    if not match:return None
    try:number=Decimal(match[1])
    except InvalidOperation:return None
    unit=match[2] or source_unit
    if key.endswith('_inr'):
        if unit in ('lpa','lakh','lakhs','lac','lacs'):number*=100000
        elif unit!='inr' and not inr:return None
    elif key=='notice_period_days':
        if unit not in ('days','day') or number!=int(number) or number>365:return None
    elif key.endswith('_years') or key=='experience_years':
        if unit not in ('year','years') or number>80:return None
    else:return None
    return number


def render_quantity(value, request, *, source_unit=''):
    number=quantity(value,request.key,source_unit=source_unit)
    if number is None:return None
    if request.key.endswith('_inr'):
        if request.unit=='lpa':number/=100000
        elif request.unit!='inr':return None
    return format(number.normalize(),'f')


def profile_fact_answer(question, profile):
    request=fact_question(question)
    if request is None:return None
    key=request.key
    if key.endswith('_inr'):
        sources=((key,'inr'),(key.removesuffix('_inr'),''))
    elif key=='notice_period_days':sources=((key,'days'),('notice_period',''))
    elif key=='experience_years':sources=((key,'years'),('total_experience_years','years'))
    else:sources=((key,'years' if key.endswith('_years') else ''),)
    values=[]
    for source,unit in sources:
        value=profile.get(source)
        if value in (None,'') or type(value) not in (str,int,float):continue
        if key.endswith('_inr') or key.endswith('_years') or key=='notice_period_days':
            rendered=render_quantity(value,request,source_unit=unit)
        else:rendered=str(value).strip()
        if rendered is None:return None
        values.append(rendered)
    if not values or len(set(values))!=1:return None
    return values[0]


def format_field_answer(question, answer, field_type):
    """Only change representation, never magnitude, range, or factual scope."""
    request=fact_question(question)
    value=str(answer).strip()
    if (field_type=='number' or (request and request.unit)) and re.fullmatch(r'(?:n/?a|not applicable)\s*[-:]\s*0(?:\.0+)?',value,re.I):
        return '0'
    if field_type=='date':
        try:return date.fromisoformat(value).isoformat()
        except ValueError:pass
        for pattern in ('%d %B %Y','%B %d %Y','%d %b %Y','%b %d %Y'):
            try:return datetime.strptime(value,pattern).date().isoformat()
            except ValueError:pass
        # Slash dates can swap day/month; never choose one interpretation.
        return None
    if field_type=='tel' and re.fullmatch(r'\+?[\d\s().-]+',value):
        return ('+' if value.startswith('+') else '')+re.sub(r'\D','',value)
    if request and request.unit:
        # A unit-bearing answer is converted; a plain numeric answer already
        # uses the unit explicitly requested on this question.
        if re.fullmatch(r'\d+(?:\.\d+)?',value):return value
        converted=render_quantity(value,request)
        if converted is not None:return converted
    if field_type=='number' and not re.fullmatch(r'[+-]?\d+(?:\.\d+)?',value):return None
    return value
