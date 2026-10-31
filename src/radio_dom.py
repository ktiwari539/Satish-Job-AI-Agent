"""Shared semantic radio labels; browser defaults never mean Yes or No."""

RADIO_DOM_JS = r"""
function agentRadioClean(value) { return String(value||'').replace(/\s+/g,' ').trim(); }
function agentRadioVisible(el) {
  if(!el||!el.isConnected)return false;
  const r=el.getBoundingClientRect(),s=getComputedStyle(el);
  return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';
}
function agentRadioOptionContainer(el) {
  const paired=el.closest('[role="radio"]');
  if(paired&&agentRadioVisible(paired))return paired;
  let node=el.parentElement;
  for(let depth=0;node&&depth<3;depth++,node=node.parentElement){
    if(node.matches('fieldset,form,[role="radiogroup"],[role="group"],body,html'))break;
    const controls=[...node.querySelectorAll('input[type="radio"],[role="radio"]')];
    if(controls.some(other=>other!==el&&!other.contains(el)&&!el.contains(other)))break;
    if(agentRadioVisible(node)&&agentRadioClean(node.innerText))return node;
  }
  return null;
}
function agentRadioLabel(el,question='') {
  const good=value=>{
    const text=agentRadioClean(value),lower=text.toLowerCase();
    return text&&text.length<=120&&!/\?$/.test(text)&&!/^(on|off|null|undefined|yes no|yes or no|no yes)$/i.test(text)&&
      lower!==agentRadioClean(question).toLowerCase();
  };
  const labels=[...el.labels||[]];
  if(el.id){const explicit=document.querySelector('label[for="'+CSS.escape(el.id)+'"]');if(explicit)labels.push(explicit);}
  const wrap=el.closest('label');if(wrap)labels.push(wrap);
  const direct=[el.getAttribute('aria-label'),...labels.filter(label=>
    ![...label.querySelectorAll('input[type="radio"],[role="radio"]')].some(other=>other!==el&&!other.contains(el)&&!el.contains(other))
  ).map(label=>label.innerText||label.textContent),
    el.matches('[role="radio"]')?(el.innerText||el.textContent):''];
  const accessible=direct.map(agentRadioClean).find(good);
  if(accessible)return accessible;
  const container=agentRadioOptionContainer(el);
  if(container){
    const leaves=[container,...container.querySelectorAll('span,label,p,div')].filter(agentRadioVisible)
      .filter(node=>!node.querySelector('span,label,p,div'));
    const values=[...new Set(leaves.map(node=>agentRadioClean(node.innerText||node.textContent)).filter(good))];
    if(values.length===1)return values[0];
  }
  const value=agentRadioClean(el.getAttribute('value'));
  // Encoded numeric/native defaults carry no visible option semantics.
  return good(value)&&!/^\d+$/.test(value)?value:'';
}
function agentRadioClickTarget(el,question='') {
  if(agentRadioVisible(el))return el;
  const label=[...el.labels||[]].find(agentRadioVisible);
  if(label)return label;
  const container=agentRadioOptionContainer(el);
  return container&&agentRadioLabel(el,question)?container:null;
}
"""
