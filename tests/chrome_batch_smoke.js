/* Full-JD worker behavior with simulated Chrome APIs, never real accounts. */
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const worker=fs.readFileSync('browser-extension/naukri/background.js','utf8');
const URL_A='https://in.indeed.com/viewjob?jk=0123456789abcdef';
const URL_B='https://in.indeed.com/viewjob?jk=fedcba9876543210';
const JD='Customer success onboarding stakeholder management SLA. '.repeat(8);

function harness({permission=true,redirect=false,mismatch=false,budget=false}={}) {
  let listener,clock=0,visited=[],removed=[],downloads=[],injected=0;
  class FixtureDate extends Date {static now(){return clock;}}
  const chrome={permissions:{contains:async()=>permission},runtime:{onMessage:{addListener:fn=>{listener=fn;}}},
    tabs:{create:async({url,active})=>{assert.equal(active,false);visited.push(url);return {id:visited.length,url};},
      get:async id=>({id,status:'complete',url:redirect?'https://accounts.google.com/signin?state=PRIVATE':visited[id-1]}),
      remove:async id=>removed.push(id)},
    scripting:{executeScript:async({target,files})=>{
      assert.deepEqual(Array.from(files),['indeed_capture.js']);injected++;
      if(budget)clock+=120001;
      return [{result:{portal:'indeed',page_kind:'detail',jobs:[{url:visited[target.tabId-1],
        title:mismatch?'Unrelated Role':'Customer Success Manager',company:'Fixture Company',location:'India',description:JD}]}}];
    }},
    downloads:{download:async data=>{assert.match(data.filename,/^indeed-jobs-details-/);
      downloads.push(JSON.parse(decodeURIComponent(data.url.split(',')[1])));return 1;}}};
  vm.runInNewContext(worker,{chrome,URL,Date:FixtureDate,setTimeout:fn=>fn()});
  return {send:message=>new Promise(resolve=>listener(message,{},resolve)),visited,removed,downloads,get injected(){return injected;}};
}
const job=url=>({url,title:'Customer Success Manager',company:'Fixture Company',location:'India'});

(async()=>{
  const denied=harness({permission:false});
  let result=await denied.send({action:'portal_enrich_jds',portal:'indeed',jobs:[job(URL_A)]});
  assert.equal(result.reason,'indeed_batch_permission_required');
  assert.equal(denied.visited.length,0);assert.equal(denied.downloads.length,0);

  const ok=harness();
  result=await ok.send({action:'portal_enrich_jds',portal:'indeed',jobs:[job(URL_A+'&tracking=PRIVATE'),job(URL_A),job(URL_B)]});
  assert.equal(result.full_jd,2);assert.equal(result.visited,2);
  assert.deepEqual(ok.visited,[URL_A,URL_B]);assert.equal(ok.removed.length,2);
  assert.equal(ok.downloads[0].portal,'indeed');
  assert.equal(ok.downloads[0].jobs[0].jd_evidence.status,'verified_job_description');
  assert.equal(JSON.stringify(ok.downloads).includes('PRIVATE'),false);

  const mismatch=harness({mismatch:true});
  result=await mismatch.send({action:'portal_enrich_jds',portal:'indeed',jobs:[job(URL_A)]});
  assert.equal(result.full_jd,0);assert.equal(mismatch.downloads[0].jobs[0].description,'');
  assert.equal(mismatch.downloads[0].jobs[0].jd_evidence.status,'job_header_identity_mismatch');
  assert.equal(mismatch.removed.length,1);

  const redirect=harness({redirect:true});
  result=await redirect.send({action:'portal_enrich_jds',portal:'indeed',jobs:[job(URL_A)]});
  assert.equal(result.full_jd,0);assert.equal(redirect.injected,0);assert.equal(redirect.removed.length,1);
  assert.equal(redirect.downloads[0].jobs[0].jd_evidence.status,'job_redirect_or_login');

  const limited=harness({budget:true});
  result=await limited.send({action:'portal_enrich_jds',portal:'indeed',jobs:[job(URL_A),job(URL_B)]});
  assert.equal(result.visited,1);assert.equal(result.considered,2);assert.equal(limited.removed.length,1);
  assert.equal(limited.downloads[0].jobs[1].jd_evidence.status,'batch_budget_exhausted');
  assert.equal(limited.downloads[0].jobs[1].description,'');

  const bad=harness();
  result=await bad.send({action:'portal_enrich_jds',portal:'indeed',jobs:[job(URL_A+'&vjk=fedcba9876543210')]});
  assert.equal(result.status,'error');assert.equal(bad.visited.length,0);
  const homepage=harness();
  result=await homepage.send({action:'naukri_enrich_jds',jobs:Array.from({length:20},()=>job('https://www.naukri.com/mnjuser/homepage'))});
  assert.equal(result.reason,'no_verified_posting_links_open_a_full_job_page');
  assert.equal(homepage.visited.length,0);assert.equal(homepage.downloads.length,0);
  process.stdout.write('Chrome full-JD batch permission/identity/budget/cleanup smoke passed; APIs simulated.\n');
})().catch(error=>{console.error(error);process.exitCode=1;});
