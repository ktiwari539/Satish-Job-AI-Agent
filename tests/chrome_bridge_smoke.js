/* Mock Chrome API/popup wiring only. Real DOM coverage is in browser fixtures. */
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const root='browser-extension/naukri/';
const source=fs.readFileSync(root+'popup.js','utf8');
const manifest=JSON.parse(fs.readFileSync(root+'manifest.json','utf8'));
assert.deepEqual(manifest.permissions,['activeTab','scripting','downloads','storage']);
assert.deepEqual(manifest.host_permissions,['https://*.naukri.com/*'],'Indeed needs only explicitly invoked activeTab');
assert.deepEqual(manifest.optional_host_permissions,['https://*.indeed.com/*'],'Indeed batch access is optional');

function harness(portal,{mismatch=false,empty=false,permission=true}={}) {
  const url=portal==='indeed'?'https://in.indeed.com/viewjob?jk=0123456789abcdef':
    portal==='naukri'?'https://www.naukri.com/job-listings-fixture-123':'https://accounts.google.com/signin';
  const elements=new Map();let calls=[],downloads=[],permissionRequests=0;
  for(const id of ['capture','enrich','enable-indeed','inspect','handoff','inspect-ats','status'])
    elements.set(id,{events:{},addEventListener(event,fn){this.events[event]=fn;}});
  const BrowserURL=class extends URL {};
  BrowserURL.createObjectURL=blob=>{downloads.push(blob);return 'blob:fixture';};
  BrowserURL.revokeObjectURL=()=>{};
  const chrome={permissions:{request:async args=>{permissionRequests++;assert.deepEqual(Array.from(args.origins),['https://*.indeed.com/*']);return permission;},
    contains:async()=>permission},tabs:{query:async()=>[{id:4,url}]},scripting:{executeScript:async args=>{
    assert.equal(args.target.tabId,4);calls.push(args);
    if(args.files?.[0]==='application_inspection.js') return [{result:{portal,schema_version:2,mode:'READ_ONLY_INSPECTION',
      job_url:mismatch?url+'-different':url,application_controls:['apply']}}];
    if(portal==='indeed')assert.deepEqual(Array.from(args.files),['indeed_capture.js']);
    else assert.equal(typeof args.func,'function');
    return [{result:{schema_version:1,portal,page_kind:'detail',jobs:empty?[]:[{url,title:'Fixture role',description:'Fixture job text'}],
      ...(empty?{diagnostics:{cards_seen:20,missing_posting_links:20}}:{})}}];
  }}};
  const doc={getElementById:id=>elements.get(id),createElement:()=>({click(){},remove(){}}),body:{appendChild(){}}};
  vm.runInNewContext(source,{document:doc,chrome,URL:BrowserURL,Blob,Date,setTimeout(){}});
  return {click:()=>elements.get('capture').events.click(),calls,downloads,elements,get permissionRequests(){return permissionRequests;}};
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
  const empty=harness('naukri',{empty:true});await empty.click();
  assert.equal(empty.calls.length,1,'no application inspection on an empty capture');
  assert.equal(JSON.parse(await empty.downloads[0].text()).jobs.length,0);
  assert.match(empty.elements.get('status').textContent,/No verified posting links/);
  const denied=harness('indeed',{permission:false});
  await denied.elements.get('enable-indeed').events.click();
  assert.equal(denied.permissionRequests,1);
  assert.match(denied.elements.get('status').textContent,/not granted/);
  await denied.elements.get('enrich').events.click();
  assert.equal(denied.calls.length,0,'denied batch never starts capture or new tabs');
  await denied.click();
  assert.equal(denied.downloads.length,1,'current-tab capture still works without batch grant');
  process.stdout.write('Chrome bridge popup/permission/identity smoke passed; Chrome APIs simulated.\n');
})().catch(error=>{console.error(error);process.exitCode=1;});
