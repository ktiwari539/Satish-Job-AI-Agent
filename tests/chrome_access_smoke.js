/* Permission failure/denial/race coverage with simulated Chrome APIs. */
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
const source = fs.readFileSync('browser-extension/naukri/indeed-access.js', 'utf8');
const flush = () => new Promise(setImmediate);
const manifest = JSON.parse(fs.readFileSync('browser-extension/naukri/manifest.json', 'utf8'));

function harness({optional=true, api=true, granted=false, requestError=null, delayedCheck=false}={}) {
  const elements = new Map();
  for (const id of ['request-access','check-access','save-diagnostic','status','diagnostic','version'])
    elements.set(id, {events:{},addEventListener(event,fn){this.events[event]=fn;}});
  let requests=0, checks=0, downloads=[], releaseCheck;
  const chrome = {runtime:{getManifest:()=>({...manifest,optional_host_permissions:optional?manifest.optional_host_permissions:[]})}};
  if (api) chrome.permissions = {
    contains:()=>{checks++;return delayedCheck?new Promise(resolve=>{releaseCheck=resolve;}):Promise.resolve(false);},
    request:args=>{requests++;assert.equal(checks,1,'no extra asynchronous check before request');
      assert.deepEqual(Array.from(args.origins),['https://*.indeed.com/*']);
      if(requestError) throw Error(requestError);
      return Promise.resolve(granted);
    }
  };
  const browserURL=class extends URL {};
  browserURL.createObjectURL=blob=>{downloads.push(blob);return 'blob:local';};
  browserURL.revokeObjectURL=()=>{};
  const document={getElementById:id=>elements.get(id),body:{appendChild(){}},createElement:()=>({click(){},remove(){}})};
  vm.runInNewContext(source,{chrome,document,URL:browserURL,Date,Blob,setTimeout(){}});
  return {elements,downloads,release:()=>releaseCheck(false),click:id=>elements.get(id).events.click(),
    get requests(){return requests;},get checks(){return checks;},
    result:()=>JSON.parse(elements.get('diagnostic').textContent)};
}

(async()=>{
  for(const granted of [true,false]) {
    const t=harness({granted});await flush();
    assert.equal(t.requests,0,'page load checks but never asks for access');
    assert.equal(t.result().code,'access_not_granted');
    await t.click('request-access');
    assert.equal(t.requests,1);assert.equal(t.result().access_granted,granted);
    assert.equal(t.result().code,granted?'access_enabled':'access_not_granted');
    assert.equal(t.elements.get('request-access').disabled,false);
  }
  const stale=harness({optional:false});await flush();await stale.click('request-access');
  assert.equal(stale.result().code,'manifest_missing_optional_host');
  assert.equal(stale.requests,0,'undeclared permission is not requested');
  assert.match(stale.elements.get('status').textContent,/Reload.*once/);
  const noApi=harness({api:false});await flush();await noApi.click('request-access');
  assert.equal(noApi.result().code,'permissions_api_unavailable');
  for(const [message,code] of [
    ['This function must be called during a user gesture','user_gesture_required'],
    ['Only permissions specified in the manifest may be requested','manifest_missing_optional_host'],
    ['Extension context invalidated.','extension_context_invalidated'],
    ['Blocked by enterprise policy','browser_policy_blocked'],
    ['Native request failed https://private.invalid/?token=DO_NOT_EXPORT user@example.invalid abcdefghijklmnopqrstuvwxyz','permission_request_failed']
  ]) {
    const t=harness({requestError:message});await flush();await t.click('request-access');
    assert.equal(t.result().code,code);
    assert.ok(t.result().browser_error);
    await t.click('save-diagnostic');const exported=await t.downloads[0].text();
    for(const privateText of ['private.invalid','DO_NOT_EXPORT','user@example.invalid','abcdefghijklmnopqrstuvwxyz'])
      assert.ok(!exported.includes(privateText),'diagnostic excludes '+privateText);
  }
  const race=harness({granted:true,delayedCheck:true});await race.click('request-access');
  race.release();await flush();
  assert.equal(race.result().code,'access_enabled','a stale load-time check cannot overwrite an enabled result');
  process.stdout.write('Chrome access diagnostics: denial, errors, manifest mismatch, privacy and race checks passed; APIs simulated.\n');
})().catch(error=>{console.error(error);process.exitCode=1;});
