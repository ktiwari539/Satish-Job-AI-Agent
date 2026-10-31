"""Shared bounded Easy Apply scope; no applicant text leaves the browser."""

WIZARD_DOM_JS = r"""
function agentWizardClean(value){return String(value||'').replace(/\s+/g,' ').trim().toLowerCase();}
function agentWizardVisible(el){
  if(!el||!el.isConnected)return false;
  const r=el.getBoundingClientRect(),s=getComputedStyle(el);
  return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';
}
function agentWizardAction(el){
  const names=[el.innerText,el.textContent,el.getAttribute('aria-label'),el.getAttribute('value')].map(agentWizardClean);
  const aliases={next:['next','next step','continue','continue to next step'],
    review:['review','review application','review your application'],
    submit:['submit','submit application','send application']};
  return Object.keys(aliases).find(key=>names.some(name=>aliases[key].includes(name)))||'';
}
function agentWizardDocuments(root){
  const selectedDocument=[...root.querySelectorAll('input[type="radio"]:checked,[role="radio"][aria-checked="true"]')]
    .some(el=>[...el.labels||[],el.closest('label'),el].filter(Boolean)
      .some(label=>agentWizardVisible(label)&&/\.(pdf|docx?)\b/i.test(label.innerText||label.textContent)));
  return selectedDocument||[...root.querySelectorAll('h2,h3,h4,legend,[role="heading"],p,span,label')]
    .filter(agentWizardVisible).some(el=>/^(resume\s*\*?|cv|resume attachment|upload (?:your )?resume)$/.test(agentWizardClean(el.innerText||el.textContent))) ||
    [...root.querySelectorAll('input[type="file"],[class*="resume"],[data-test*="resume"]')]
      .some(el=>agentWizardVisible(el)||[...el.labels||[]].some(agentWizardVisible));
}
function agentWizardRoot({requireDocument=false}={}){
  const acceptable=root=>!requireDocument||agentWizardDocuments(root);
  const dialogs=[...document.querySelectorAll('.jobs-easy-apply-modal,.artdeco-modal,[role="dialog"]')].filter(agentWizardVisible);
  const inner=dialogs.filter(node=>!dialogs.some(other=>other!==node&&node.contains(other)));
  if(inner.length===1&&acceptable(inner[0]))return inner[0];
  if(inner.length>1)return null;
  const inline=[...document.querySelectorAll('.jobs-easy-apply-content,.jobs-easy-apply-form,[data-test*="easy-apply-form"]')].filter(agentWizardVisible);
  const known=inline.find(node=>inline.every(other=>node.contains(other)));
  if(known&&acceptable(known))return known;
  // Read short progress text nodes, including a counter combined with a
  // percentage or an icon. Never choose document.body as a wizard root.
  const markers=[];
  const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  for(let node=walker.nextNode();node;node=walker.nextNode()){
    if(node.parentElement?.closest('script,style,textarea,input,select,[contenteditable="true"]'))continue;
    const value=agentWizardClean(node.textContent);
    if(value.length>120||!/(?<!\d)\d{1,2}\s*\/\s*\d{1,2}\s*pages?\b/i.test(value))continue;
    if(agentWizardVisible(node.parentElement))markers.push(node.parentElement);
    if(markers.length>12)return null;
  }
  const candidates=[];
  for(const marker of [...new Set(markers)]){
    let node=marker.parentElement;
    for(let depth=0;node&&depth<12;depth++,node=node.parentElement){
      if(node.matches('body,html'))break;
      if(!agentWizardVisible(node))continue;
      const actions=[...node.querySelectorAll('button,[role="button"],input[type="button"],input[type="submit"]')]
        .filter(agentWizardVisible).map(agentWizardAction).filter(Boolean);
      if(!actions.length)continue;
      const fields=[...node.querySelectorAll('input,textarea,select,[role="radio"]')]
        .some(el=>!el.disabled&&(agentWizardVisible(el)||[...el.labels||[]].some(agentWizardVisible)));
      const finalDocument=actions.includes('submit')&&agentWizardDocuments(node);
      if((fields||finalDocument)&&acceptable(node)){candidates.push(node);break;}
    }
  }
  const unique=[...new Set(candidates)];
  // Repeated header/footer markers must describe one nested wizard, rather
  // than selecting one of two independent forms or a background sidebar.
  return unique.find(node=>unique.every(other=>node===other||node.contains(other)))||null;
}
"""


def mark_active_wizard(page):
    """Mark a read-only scope for fresh trusted clicks; no form values returned."""
    script="""() => {"""+WIZARD_DOM_JS+r"""
      for(const node of document.querySelectorAll('[data-agent-wizard-root]'))node.removeAttribute('data-agent-wizard-root');
      const root=agentWizardRoot();
      if(!root)return {status:'missing'};
      root.setAttribute('data-agent-wizard-root','active');
      return {status:'found'};
    }"""
    try:
        result=page.evaluate(script)
        return result.get('status','unavailable') if isinstance(result,dict) else 'unavailable'
    except Exception:
        return 'unavailable'
