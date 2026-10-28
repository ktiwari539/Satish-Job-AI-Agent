/* Mock Chrome API/popup wiring only. Real DOM coverage is in browser fixtures. */
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const root='browser-extension/naukri/';
const source=fs.readFileSync(root+'popup.js','utf8');
const manifest=JSON.parse(fs.readFileSync(root+'manifest.json','utf8'));
assert.deepEqual(manifest.permissions,['activeTab','scripting','downloads','storage']);
assert.deepEqual(manifest.host_permissions,['https://*.naukri.com/*'],'Indeed needs only explicitly invoked activeTab');

function harness(portal,{mismatch=false}={}) {
  const url=portal==='indeed'?'https://in.indeed.com/viewjob?jk=0123456789abcdef':
    portal==='naukri'?'https://www.naukri.com/job-listings-fixture-123':'https://accounts.google.com/signin';
  const elements=new Map();let calls=[],downloads=[];
  for(const id of ['capture','enrich','inspect','handoff','inspect-ats','status'])
    elements.set(id,{events:{},addEventListener(event,fn){this.events[event]=fn;}});
  const BrowserURL=class extends URL {};
  BrowserURL.createObjectURL=blob=>{downloads.push(blob);return 'blob:fixture';};
  BrowserURL.revokeObjectURL=()=>{};
  const chrome={tabs:{query:async()=>[{id:4,url}]},scripting:{executeScript:async args=>{
    assert.equal(args.target.tabId,4);calls.push(args);
    if(args.files?.[0]==='application_inspection.js') return [{result:{portal,schema_version:2,mode:'READ_ONLY_INSPECTION',
      job_url:mismatch?url+'-different':url,application_controls:['apply']}}];
    if(portal==='indeed')assert.deepEqual(Array.from(args.files),['indeed_capture.js']);
    else assert.equal(typeof args.func,'function');
    return [{result:{schema_version:1,portal,page_kind:'detail',jobs:[{url,title:'Fixture role',description:'Fixture job text'}]}}];
  }}};
  const doc={getElementById:id=>elements.get(id),createElement:()=>({click(){},remove(){}}),body:{appendChild(){}}};
  vm.runInNewContext(source,{document:doc,chrome,URL:BrowserURL,Blob,Date,setTimeout(){}});
  return {click:()=>elements.get('capture').events.click(),calls,downloads,elements};
}

(async()=>{
  for(const portal of ['naukri','indeed']) {
    const test=harness(portal);await test.click();
    assert.equal(test.calls.length,2,'one capture plus exact-job application inspection');
    const payload=JSON.parse(await test.downloads[0].text());
    assert.equal(payload.portal,portal);
    assert.equal(payload.application_inspection.job_url,payload.jobs[0].url);
    assert.equal(test.elements.get('capture').disabled,false);
  }
  const mismatch=harness('indeed',{mismatch:true});await mismatch.click();
  assert.equal(mismatch.downloads.length,0,'job changed between capture/inspection: no mixed export');
  assert.match(mismatch.elements.get('status').textContent,/changed/);
  const foreign=harness('google');await foreign.click();
  assert.equal(foreign.calls.length,0,'Google and unrelated tabs are never injected');
  assert.equal(foreign.downloads.length,0);
  process.stdout.write('Chrome bridge popup/permission/identity smoke passed; Chrome APIs simulated.\n');
})().catch(error=>{console.error(error);process.exitCode=1;});
