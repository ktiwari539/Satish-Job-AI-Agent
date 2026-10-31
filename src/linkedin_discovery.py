"""Bounded, read-only LinkedIn search discovery with structural diagnostics.

No login, clicks, form values, page HTML, screenshots or credentials. Public
job metadata is returned in memory; persisted evidence contains counts only.
"""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, urlsplit

from browser_extractors import RawJobCard, normalize_browser_cards
from dedupe import canonical_company
from extractor import normalize_text


_SEARCH_PROBE = r"""() => {
  const visible = el => {
    if (!el || !el.isConnected) return false;
    const r=el.getBoundingClientRect(),s=getComputedStyle(el);
    return r.width>0 && r.height>0 && s.display!=='none' && s.visibility!=='hidden';
  };
  const clean = v => String(v||'').replace(/\s+/g,' ').trim();
  const text = el => {
    if (!el || !visible(el)) return '';
    // Exclude screen-reader copies and verification badges from job titles.
    const clone=el.cloneNode(true);
    clone.querySelectorAll('.visually-hidden,.sr-only,[aria-hidden="true"],script,style').forEach(n=>n.remove());
    return clean(clone.textContent).slice(0,600);
  };
  const all = (root,selector,max=200) => [...root.querySelectorAll(selector)].slice(0,max);
  const firstText = (root,selectors) => {
    for (const selector of selectors) {
      for (const el of all(root,selector,12)) { const value=text(el); if(value) return value; }
    }
    return '';
  };
  const detail='.jobs-search__job-details--container,.jobs-search__job-details,.jobs-details,.scaffold-layout__detail,[data-testid="job-details"],[role="dialog"]';
  const regions=all(document,'.jobs-search-results-list,.jobs-search-results__list,.jobs-search__results-list,.scaffold-layout__list,[data-testid="job-search-results"],[role="list"][aria-label*="jobs" i]');
  const roots=regions.length?regions:(all(document,'main').length?all(document,'main'):[document]);
  const cardSelector='li.scaffold-layout__list-item,li.jobs-search-results__list-item,.job-card-container,.base-search-card,.base-card,[data-job-id],[data-occludable-job-id],[data-entity-urn^="urn:li:jobPosting:"],[role="listitem"],article';
  const excluded = el => !!el.closest(detail+',header,nav,footer') || (!regions.length && !!el.closest('aside'));
  const candidates=new Set();
  for (const root of roots) {
    for(const el of all(root,'[data-job-id],[data-occludable-job-id],[data-entity-urn^="urn:li:jobPosting:"]'))if(visible(el)&&!excluded(el))candidates.add(el);
    for(const a of all(root,'a[href*="/jobs/view/"],a[href*="currentJobId="]',400)) {
      if(!visible(a)||excluded(a))continue;
      // A job anchor itself is a valid narrow scope when card classes change.
      // Missing company/location must then be recovered from the exact job.
      const card=a.closest(cardSelector)||a;
      if(card&&visible(card)&&!excluded(card))candidates.add(card);
      candidates.add(a);
    }
    for(const el of all(root,cardSelector)) if(visible(el)&&!excluded(el)) candidates.add(el);
  }
  const rows=[];
  for(const node of [...candidates].slice(0,200)) {
    let root=node;
    const title=firstText(root,['a.job-card-list__title--link','a.job-card-list__title','.job-card-container__link','[data-testid="job-card-title"]','.base-search-card__title','.artdeco-entity-lockup__title','h2','h3','h4','a[href*="/jobs/view/"]'])||(root.matches('a[href]')?text(root):'');
    const company=firstText(root,['.artdeco-entity-lockup__subtitle','.job-card-container__primary-description','.base-search-card__subtitle','[data-testid="company-name"]','[data-testid="job-card-company-name"]','[itemprop="hiringOrganization"]','a[href*="/company/"]']);
    const location=firstText(root,['.artdeco-entity-lockup__caption','.job-card-container__metadata-item','.job-search-card__location','[data-testid="job-location"]','[data-testid="job-card-location"]','[itemprop="jobLocation"]']);
    const ids=[];
    const addIds=el=>{
      for(const attr of ['data-job-id','data-occludable-job-id']){
        const id=el.getAttribute(attr);if(id)ids.push(id);
      }
      const urn=el.getAttribute('data-entity-urn')||'';
      if(urn.startsWith('urn:li:jobPosting:'))ids.push(urn.slice('urn:li:jobPosting:'.length));
    };
    addIds(root);
    const rootIds=ids.slice();
    for(const el of all(root,'[data-job-id],[data-occludable-job-id],[data-entity-urn^="urn:li:jobPosting:"]',20))addIds(el);
    let parent=root.parentElement;
    for(let depth=0;parent&&depth<6;depth++,parent=parent.parentElement){
      if(parent.tagName==='MAIN'||roots.includes(parent))break;
      addIds(parent);
    }
    const hrefs=all(root,'a[href*="/jobs/view/"],a[href*="currentJobId="]',12).filter(visible).map(a=>a.href);
    if(root.matches('a[href]'))hrefs.push(root.href);
    rows.push({title,company,location,ids,root_ids:rootIds,hrefs});
  }
  const headings=all(document,'main h1,main h2,main h3,[role="heading"],.jobs-search-no-results-banner,[data-testid="no-results"],[role="alert"]',60).filter(visible).map(el=>clean(el.innerText).toLowerCase());
  const hint=pattern=>headings.some(value=>pattern.test(value));
  const loginForm=all(document,'form[action*="/login"],form[action*="/uas/login"]',10).some(el=>visible(el)&&!!el.querySelector('input'));
  const password=all(document,'input[type="password"]',10).some(visible);
  const busy=roots.some(root=>root.getAttribute?.('aria-busy')==='true');
  return {rows,signals:{
    ready_complete:document.readyState==='complete',
    main_count:Math.min(document.querySelectorAll('main').length,100),
    legacy_containers:Math.min(document.querySelectorAll('li.scaffold-layout__list-item,li.jobs-search-results__list-item,.job-card-container').length,1000),
    search_regions:regions.length,candidate_cards:Math.min(candidates.size,200),
    job_links:Math.min(document.querySelectorAll('a[href*="/jobs/view/"]').length,1000),
    job_id_nodes:Math.min(document.querySelectorAll('[data-job-id],[data-occludable-job-id],[data-entity-urn^="urn:li:jobPosting:"]').length,1000),
    iframe_count:Math.min(document.querySelectorAll('iframe').length,100),
    body_chars:Math.min((document.body?.innerText||'').length,100000),
    loading:busy||roots.some(root=>all(root,'[role="progressbar"],.artdeco-loader,.loading-spinner',30).some(el=>visible(el)&&!el.closest(detail))),
    results_busy:busy,
    login:password||loginForm||hint(/^(?:sign in(?: to linkedin)?|join linkedin)(?:[.! ]|$)/),
    challenge:hint(/verify (?:your identity|you are human)|security verification|security checkpoint|complete the captcha/),
    no_results:hint(/no matching jobs|no jobs found|no results found|we couldn.t find (?:any )?jobs|no jobs matching/),
    page_error:hint(/something went wrong|unable to load jobs|temporarily unavailable/)
  }};
}"""

BOOL_SIGNALS=('ready_complete','loading','results_busy','login','challenge','no_results','page_error')
COUNT_SIGNALS=('main_count','legacy_containers','search_regions','candidate_cards','job_links','job_id_nodes','iframe_count','body_chars')


def route_state(url, expected_query=None):
    try:
        parsed=urlsplit(url)
        if parsed.scheme!='https' or (parsed.hostname or '').lower() not in ('www.linkedin.com','linkedin.com') or parsed.username or parsed.password or parsed.port not in (None,443):
            return 'untrusted_origin'
        path=parsed.path.rstrip('/')
        if path.startswith(('/checkpoint','/challenge')):return 'challenge'
        if path.startswith(('/login','/uas/login','/authwall','/signup')):return 'login'
        if path not in ('/jobs/search','/jobs/search-results'):return 'other_linkedin_route'
        if expected_query is not None:
            values=parse_qs(parsed.query,keep_blank_values=True).get('keywords',[])
            if len(values)!=1 or normalize_text(values[0])!=normalize_text(expected_query):return 'search_context_mismatch'
        return 'search'
    except (ValueError,TypeError,AttributeError):
        return 'untrusted_origin'


def _link_id(url):
    try:
        parsed=urlsplit(url)
        if parsed.scheme!='https' or (parsed.hostname or '').lower() not in ('www.linkedin.com','linkedin.com') or parsed.username or parsed.password or parsed.port not in (None,443):return ''
        query=parse_qs(parsed.query,keep_blank_values=True)
        match=re.fullmatch(r'/jobs/view/(?:[^/?]+-)?([0-9]{7,15})/?',parsed.path)
        if match:
            identifier=match[1]
            if 'currentJobId' in query and query['currentJobId']!=[identifier]:return ''
            return identifier
        if parsed.path.rstrip('/') in ('/jobs/search','/jobs/search-results'):
            ids=query.get('currentJobId',[])
            if len(ids)==1 and re.fullmatch(r'[0-9]{7,15}',ids[0]):return ids[0]
        return ''
    except (ValueError,TypeError,AttributeError):return ''


def decode_probe(payload):
    """Validate the browser response; diagnostics never reflect page strings."""
    counters=dict(missing_title=0,missing_identity=0,invalid_links=0,identity_conflicts=0,
                  duplicate_cards=0,metadata_pending=0,verified_cards=0)
    if not isinstance(payload,dict) or not isinstance(payload.get('signals'),dict) or not isinstance(payload.get('rows'),list):
        return [],dict(probe_available=False,**counters)
    signals=payload['signals']
    evidence={key:signals.get(key) is True for key in BOOL_SIGNALS}
    evidence.update({key:min(max(signals.get(key),0),100000) if type(signals.get(key)) is int else 0 for key in COUNT_SIGNALS})
    evidence['probe_available']=True
    by_id={};conflicted=set()
    for row in payload['rows'][:200]:
        if not isinstance(row,dict):continue
        title,company,location=(row.get(key) for key in ('title','company','location'))
        if any(not isinstance(v,str) or len(v)>600 for v in (title,company,location)):continue
        if normalize_text(title) in ('','view job','view more','easy apply','apply','see jobs'):
            counters['missing_title']+=1;continue
        ids=row.get('ids');hrefs=row.get('hrefs')
        if not isinstance(ids,list) or len(ids)>150 or not isinstance(hrefs,list) or len(hrefs)>20:continue
        observed=set()
        malformed=False
        for value in ids:
            if not isinstance(value,str) or not re.fullmatch(r'[0-9]{7,15}',value):malformed=True
            else:observed.add(value)
        for href in hrefs:
            value=_link_id(href)
            if not value:counters['invalid_links']+=1;malformed=True
            else:observed.add(value)
        if malformed or len(observed)>1:
            counters['identity_conflicts']+=1
            # A wrapper containing several jobs must not suppress independent
            # child cards. Only contradictory declared roots poison an ID.
            root_ids=row.get('root_ids',ids)
            if isinstance(root_ids,list):conflicted.update(value for value in root_ids if isinstance(value,str) and re.fullmatch(r'[0-9]{7,15}',value))
            continue
        if not observed:counters['missing_identity']+=1;continue
        identifier=next(iter(observed))
        card=RawJobCard(title.strip(),company.strip(),location.strip(),
            'https://www.linkedin.com/jobs/view/'+identifier+'/',external_id=identifier)
        previous=by_id.get(identifier)
        if previous:
            counters['duplicate_cards']+=1
            mismatch=(normalize_text(previous.title)!=normalize_text(card.title) or
                (previous.company and card.company and canonical_company(previous.company)!=canonical_company(card.company)) or
                (previous.location and card.location and normalize_text(previous.location)!=normalize_text(card.location)))
            if mismatch:
                conflicted.add(identifier);counters['identity_conflicts']+=1
            elif (bool(card.company)+bool(card.location))>(bool(previous.company)+bool(previous.location)):
                by_id[identifier]=card
        else:by_id[identifier]=card
    cards=[card for identifier,card in by_id.items() if identifier not in conflicted]
    counters['metadata_pending']=sum(not card.company or not card.location for card in cards)
    counters['verified_cards']=len(cards)
    evidence.update(counters)
    return cards,evidence


def probe_search(page, *, expected_query=None):
    route=route_state(str(getattr(page,'url','') or ''),expected_query)
    if route!='search':return [],dict(route=route,probe_available=False,verified_cards=0)
    try:payload=page.evaluate(_SEARCH_PROBE)
    except Exception:payload=None
    # A navigation may finish while the DOM probe is in flight. Never release
    # cards from a page whose route or search context has since changed.
    current_route=route_state(str(getattr(page,'url','') or ''),expected_query)
    if current_route!='search':return [],dict(route=current_route,probe_available=False,verified_cards=0)
    cards,evidence=decode_probe(payload)
    return cards,dict(route=route,**evidence)


def discovery_status(evidence, *, exhausted=False):
    route=evidence.get('route')
    if route=='challenge' or evidence.get('challenge'):return 'SEARCH_CHALLENGE'
    if route=='login' or evidence.get('login'):return 'SEARCH_LOGIN_REQUIRED'
    if route=='search_context_mismatch':return 'SEARCH_CONTEXT_MISMATCH'
    if route!='search':return 'SEARCH_ROUTE_MISMATCH'
    if evidence.get('page_error'):return 'SEARCH_PAGE_ERROR'
    if evidence.get('results_busy'):return 'SEARCH_LOADING_TIMEOUT' if exhausted else 'SEARCH_LOADING'
    if evidence.get('no_results'):return 'SEARCH_NO_RESULTS'
    if evidence.get('verified_cards',0)>0:return 'DISCOVERED'
    if not evidence.get('probe_available'):return 'SEARCH_PROBE_UNAVAILABLE'
    if evidence.get('loading') or not evidence.get('ready_complete'):return 'SEARCH_LOADING_TIMEOUT' if exhausted else 'SEARCH_LOADING'
    if evidence.get('identity_conflicts'):return 'SEARCH_IDENTITY_CONFLICT'
    if evidence.get('candidate_cards') or evidence.get('job_links') or evidence.get('job_id_nodes'):return 'SEARCH_CARD_METADATA_INCOMPLETE'
    return 'SEARCH_MARKUP_UNSUPPORTED'


@dataclass(frozen=True)
class SearchDiscovery:
    jobs: tuple
    status: str
    evidence: dict


def discover_search(page, taxonomy, *, expected_query=None, timeout_ms=12000, poll_ms=400):
    if type(timeout_ms) is not int or not 0<=timeout_ms<=15000 or type(poll_ms) is not int or not 1<=poll_ms<=1000:
        raise ValueError('invalid_search_probe_budget')
    deadline=time.monotonic()+timeout_ms/1000
    maximum=timeout_ms//poll_ms+2
    terminal={'DISCOVERED','SEARCH_CHALLENGE','SEARCH_LOGIN_REQUIRED','SEARCH_CONTEXT_MISMATCH',
              'SEARCH_ROUTE_MISMATCH','SEARCH_NO_RESULTS','SEARCH_PAGE_ERROR'}
    for attempt in range(maximum):
        if page.is_closed():
            from browser_runtime import BrowserRuntimeUnavailable
            raise BrowserRuntimeUnavailable(reason_code='browser_connection_lost')
        cards,evidence=probe_search(page,expected_query=expected_query)
        exhausted=time.monotonic()>=deadline or attempt+1==maximum
        status=discovery_status(evidence,exhausted=exhausted)
        if status in terminal or exhausted:break
        page.wait_for_timeout(min(poll_ms,max(1,int((deadline-time.monotonic())*1000))))
    jobs=tuple(normalize_browser_cards('linkedin',cards,taxonomy)) if status=='DISCOVERED' else ()
    return SearchDiscovery(jobs,status,dict(schema_version=1,status=status,attempts=attempt+1,
        wait_budget_ms=timeout_ms,**evidence,submission_enabled=False,application_form_exercised=False))


def write_discovery_evidence(evidence, path='data/certification/linkedin-discovery-latest.json'):
    """Persist the fixed structural schema before the browser closes."""
    target=Path(path);target.parent.mkdir(parents=True,exist_ok=True)
    import tempfile
    descriptor,name=tempfile.mkstemp(prefix=target.name+'.',dir=target.parent)
    temporary=Path(name)
    try:
        with os.fdopen(descriptor,'w') as output:output.write(json.dumps(evidence,sort_keys=True,indent=2)+'\n')
        os.replace(temporary,target)
    finally:
        if temporary.exists():temporary.unlink()
    return str(target)


def main():
    """Collect one current search diagnosis without applicant files or forms."""
    import argparse
    from browser_runtime import BrowserRuntimeConfig, BrowserRuntimeUnavailable, PlaywrightSession
    from browser_portals import LinkedInBrowserAdapter
    from scheduled_review import acquire_run_lock
    parser=argparse.ArgumentParser(description='Inspect LinkedIn search in the existing agent browser. Never logs in, fills, or submits.')
    parser.add_argument('--profile-dir',default='browser-profile')
    parser.add_argument('--query',default='Customer Success Manager')
    parser.add_argument('--location',default='India')
    parser.add_argument('--report',default='data/certification/linkedin-discovery-latest.json')
    parser.add_argument('--headless',action='store_true')
    args=parser.parse_args()
    descriptor=None
    try:
        descriptor=acquire_run_lock('data/review-worker.lock')
        if descriptor is None:
            print(json.dumps(dict(status='review_worker_already_running',submission_enabled=False)))
            return 4
        with PlaywrightSession(BrowserRuntimeConfig(user_data_dir=args.profile_dir,headless=args.headless)) as runtime:
            try:
                LinkedInBrowserAdapter(runtime.page).open_search(args.query,args.location,easy_apply_only=True)
                result=discover_search(runtime.page,(),expected_query=args.query)
                evidence=result.evidence
            except BrowserRuntimeUnavailable:raise
            except Exception:
                _,probe=probe_search(runtime.page,expected_query=args.query)
                status=discovery_status(probe,exhausted=True)
                evidence=dict(schema_version=1,status=status if status!='DISCOVERED' else 'SEARCH_NAVIGATION_FAILED',
                              **probe,submission_enabled=False,application_form_exercised=False)
            write_discovery_evidence(evidence,args.report)
        print(json.dumps(dict(report=args.report,verification_scope='local_read_only_search_probe',**evidence),sort_keys=True))
        return 0 if evidence['status']=='DISCOVERED' else 4
    except BrowserRuntimeUnavailable as exc:
        evidence=dict(status='browser_runtime_unavailable',reason_code=exc.reason_code,
                      submission_enabled=False,application_form_exercised=False)
        write_discovery_evidence(evidence,args.report)
        print(json.dumps(evidence,sort_keys=True))
        return 2
    finally:
        if descriptor is not None:os.close(descriptor)


if __name__=='__main__':raise SystemExit(main())
