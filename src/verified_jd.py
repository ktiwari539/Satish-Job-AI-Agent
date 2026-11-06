"""Bounded JD hydration, exact-ID alternatives and structural evidence only."""
from dataclasses import replace
import time
from jd_enrichment import JD_SELECTORS, _read_first_visible, enrich_job_from_text, EnrichmentResult
from linkedin_exact_job import parse_linkedin_target, _structured_details, _safe_page_state
from linkedin_public_metadata import fetch_public_exact_linkedin_job
from dedupe import canonical_company, titles_similar
from browser_runtime import BrowserRuntimeUnavailable
from portal_preparation import exact_job_page


def _open(page):
    if page.is_closed():
        raise BrowserRuntimeUnavailable(reason_code='browser_connection_lost')


def _probe(page, portal):
    """No HTML, job text, selectors from the page or input values leave here."""
    try:
        rows = page.evaluate("""selectors => selectors.map((selector, index) => {
          const nodes = [...document.querySelectorAll(selector)].slice(0,12);
          const visible = nodes.filter(el => {
            const r=el.getBoundingClientRect(),s=getComputedStyle(el);
            return r.width>0 && r.height>0 && s.display!=='none' && s.visibility!=='hidden';
          });
          return {index, matched:nodes.length, visible:visible.length,
            max_chars:Math.max(0,...visible.map(el => Math.min((el.innerText||'').trim().length,100000)))};
        })""", list(JD_SELECTORS.get(portal, ())))
    except Exception:
        rows = []
    safe = []
    if isinstance(rows,list):
        for row in rows[:20]:
            if isinstance(row,dict):
                safe.append({key:min(max(row.get(key,0),0),100000) if type(row.get(key)) is int else 0
                             for key in ('index','matched','visible','max_chars')})
    state = _safe_page_state(page) if portal == 'linkedin' else {}
    allowed = ('security_checkpoint','sign_in_interstitial','listing_unavailable','empty_or_unrendered_page',
               'no_job_details_in_dom','job_markup_unrecognized','probe_unavailable')
    return dict(selectors=safe,page_state=state.get('page_state') if state.get('page_state') in allowed else 'probe_unavailable')


def read_verified_job_description(page, job, taxonomy, *, allow_public_fallback=False, max_probes=21):
    """Never use page/footer text or a different listing as a job description."""
    evidence = dict(job_key=job.key,source=job.source,read_route='none',description_chars=0,probes=0)
    target = parse_linkedin_target(job.url) if job.source == 'linkedin' else None
    text = ''
    reason = 'jd_missing_selector_layout'
    deadline = time.monotonic()+8
    for attempt in range(max(1,min(int(max_probes),21))):
        _open(page)
        if not exact_job_page(page,job):
            reason = 'jd_job_identity_mismatch'
            break
        evidence['probes'] = attempt+1
        probe = _probe(page,job.source)
        evidence.update(probe)
        state = probe['page_state']
        stopped = {'security_checkpoint':'jd_security_challenge','sign_in_interstitial':'jd_authentication_required',
                   'listing_unavailable':'job_listing_unavailable'}
        if state in stopped:
            reason = stopped[state]
            break
        text = _read_first_visible(page,JD_SELECTORS.get(job.source,()),min_chars=120,deadline=deadline)
        if len(text) >= 120:
            evidence.update(read_route='visible_scoped',description_chars=len(text),reason='')
            return enrich_job_from_text(job,text,taxonomy),evidence
        if target is not None:
            structured = _structured_details(page,target,deadline=deadline)
            if structured is not None:
                title,company,location,description = structured
                if canonical_company(company) != canonical_company(job.company) or not titles_similar(title,job.title):
                    reason = 'jd_listing_metadata_conflict'
                    break
                evidence.update(read_route='exact_job_structured',description_chars=len(description),reason='')
                verified=replace(job,title=title,company=company,location=location)
                return enrich_job_from_text(verified,description,taxonomy),evidence
        reason = 'jd_incomplete_content' if text else 'jd_missing_selector_layout'
        remaining=deadline-time.monotonic()
        if remaining <= 0:
            break
        if attempt+1 < max(1,min(int(max_probes),21)):
            page.wait_for_timeout(min(400,max(1,int(remaining*1000))))
    _open(page)
    if target is not None and allow_public_fallback and reason in ('jd_incomplete_content','jd_missing_selector_layout'):
        try:
            public = fetch_public_exact_linkedin_job(target.url,target,taxonomy)
            if canonical_company(public.company) != canonical_company(job.company) or not titles_similar(public.title,job.title):
                reason = 'jd_listing_metadata_conflict'
            else:
                evidence.update(read_route='public_same_id',description_chars=len(public.description),reason='')
                return EnrichmentResult(public,True),evidence
        except ValueError as exc:
            # Exception strings are never exported (URLs and bodies can contain private data).
            evidence['public_fallback_status'] = 'unavailable'
    evidence.update(description_chars=len(text),reason=reason)
    return EnrichmentResult(job,False,reason),evidence
