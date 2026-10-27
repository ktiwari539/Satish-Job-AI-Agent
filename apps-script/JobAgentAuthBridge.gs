/* Deploy only after reviewing the private setup in docs/AUTH_AND_JD_CHECKPOINT.md.
 * Secrets belong in Script Properties, never in this source or logs.
 * Advanced Gmail service uses gmail.readonly; this script never sends mail.
 */
function doGet() { return bridgeJson_({ok:false}); }

function bridgeJson_(value) {
  return ContentService.createTextOutput(JSON.stringify(value)).setMimeType(ContentService.MimeType.JSON);
}

function bridgeHex_(bytes) {
  return bytes.map(x => ('0'+((x+256)%256).toString(16)).slice(-2)).join('');
}

function bridgeDigest_(value) {
  return bridgeHex_(Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,value,Utilities.Charset.UTF_8));
}

function bridgeAccount_(properties,portal) {
  let email=properties.getProperty('EMAIL_'+portal.toUpperCase())||'';
  let password=properties.getProperty('PASSWORD_'+portal.toUpperCase())||'';
  if (!email && !password) {
    const allowed=(properties.getProperty('SHARED_PORTALS')||'').split(',').map(s=>s.trim());
    if (allowed.includes(portal)) {
      email=properties.getProperty('SHARED_EMAIL')||'';
      password=properties.getProperty('SHARED_PASSWORD')||'';
    }
  }
  if (!email.trim() || !password || bridgeEmails_(email).length!==1||bridgeEmails_(email)[0]!==email.trim().toLowerCase()) throw Error('account_unavailable');
  return {email:email.trim(),password};
}

function doPost(event) {
  let lock;
  try {
    const raw=event&&event.postData&&event.postData.contents;
    if (typeof raw!=='string'||raw.length>4096) throw Error('invalid');
    const request=JSON.parse(raw),now=Date.now();
    const validOperation=(['linkedin','naukri','indeed'].includes(request.portal)&&['credentials','email_otp'].includes(request.operation))||
      (request.portal==='control'&&request.operation==='control_snapshot');
    if (request.version!==1||!validOperation||
        !Number.isSafeInteger(request.requested_at_ms)||Math.abs(now-request.requested_at_ms)>60000||
        !Number.isSafeInteger(request.issued_after_ms)||
        !/^[a-f0-9]{32}$/.test(request.nonce)||!/^[a-f0-9]{64}$/.test(request.signature)||
        typeof request.account_email!=='string'||request.account_email.length>254||/[\r\n]/.test(request.account_email)) throw Error('invalid');
    const properties=PropertiesService.getScriptProperties(),key=properties.getProperty('BRIDGE_SHARED_KEY')||'';
    if (key.length<32) throw Error('unconfigured');
    const canonical=['version','operation','portal','requested_at_ms','nonce','issued_after_ms','account_email']
      .map(k=>String(request[k])).join('\n');
    const expected=bridgeHex_(Utilities.computeHmacSha256Signature(canonical,key,Utilities.Charset.UTF_8));
    let different=0;
    for (let i=0;i<expected.length;i++) different|=expected.charCodeAt(i)^request.signature.charCodeAt(i);
    if (different) throw Error('unauthorized');
    lock=LockService.getScriptLock();
    if (!lock.tryLock(1000)) throw Error('busy');
    const nonceKey='request_'+request.nonce;
    if (properties.getProperty(nonceKey)) throw Error('replay');
    properties.setProperty(nonceKey,String(now));
    const saved=properties.getProperties();
    Object.keys(saved).filter(k=>k.startsWith('request_')&&Number(saved[k])<now-120000).slice(0,100)
      .forEach(k=>properties.deleteProperty(k));
    if (request.operation==='control_snapshot') return bridgeJson_({ok:true,data:bridgeControlSnapshot_(properties)});
    const account=bridgeAccount_(properties,request.portal);
    if (request.operation==='credentials') return bridgeJson_({ok:true,data:account});
    if (request.account_email.toLowerCase()!==account.email.toLowerCase()||
        request.issued_after_ms>now||request.issued_after_ms<now-300000) throw Error('challenge_mismatch');
    const data=bridgeEmailCode_(properties,request,now);
    return bridgeJson_({ok:true,data});
  } catch (_) {
    // Never echo request data, exceptions, credentials, message headers or bodies.
    return bridgeJson_({ok:false});
  } finally {
    if (lock) lock.releaseLock();
  }
}

function bridgeControlSnapshot_(properties) {
  const id=properties.getProperty('CONTROL_SHEET_ID')||'';
  if (!/^[A-Za-z0-9_-]{20,150}$/.test(id)) throw Error('control_unconfigured');
  const result=Sheets.Spreadsheets.Values.batchGet(id,{ranges:["'Config'!A1:C200","'Question_Bank'!A1:H1001"],
    valueRenderOption:'UNFORMATTED_VALUE',dateTimeRenderOption:'FORMATTED_STRING'});
  const ranges=result.valueRanges||[];
  if (ranges.length!==2) throw Error('control_schema');
  const rows=ranges[0].values||[],questions=ranges[1].values||[];
  const allowed=new Set(['agent_enabled','operating_mode','profile_name','current_location','current_company',
    'current_role','experience_years','preferred_roles','preferred_locations','remote_allowed','current_ctc_inr',
    'expected_ctc_inr','notice_period_days','auto_apply_score','daily_application_cap','target_daily_cap_after_qa',
    'india_work_authorization','outside_india_sponsorship','excluded_companies','excluded_keywords','resume_filename',
    'portfolio_url','linkedin_url','schedule_1_local','schedule_2_local','timezone','environment','agent_version','last_profile_review']);
  const config=rows.slice(0,3).map(r=>r.slice(0,2));
  for (const row of rows.slice(3,200)) {
    if (!row||!row[0]) continue;
    if (/password|credential|secret|token|login_email/i.test(String(row[0]))) throw Error('private_credentials_required');
    if(allowed.has(String(row[0]))) config.push(row.slice(0,2));
  }
  for (const row of questions.slice(1,1001)) {
    const question=String(row&&row[0]||'').toLowerCase().replace(/[^a-z0-9]+/g,' ');
    if(/\b(password|otp|one time code|verification code|shared key|api key)\b/.test(question)) throw Error('private_credentials_required');
  }
  const snapshot={schema_version:1,config_rows:config,
    question_rows:questions.slice(0,1001).map((r,i)=>i===0?r.slice(0,8):r.slice(0,7).concat(['']))};
  if(JSON.stringify(snapshot).length>900000) throw Error('control_oversize');
  return snapshot;
}

function bridgeEmails_(text) {
  return (String(text||'').toLowerCase().match(/[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}/g)||[]);
}

function bridgePlainText_(payload) {
  let pending=[payload],result='',visited=0;
  while(pending.length&&visited++<40&&result.length<65536) {
    const item=pending.pop();
    if (!item) continue;
    if (item.mimeType==='text/plain'&&item.body&&item.body.data) {
      result+='\n'+Utilities.newBlob(Utilities.base64DecodeWebSafe(item.body.data)).getDataAsString('UTF-8');
    }
    if (Array.isArray(item.parts)) pending.push(...item.parts.slice(0,20));
  }
  return result.slice(0,65536);
}

function bridgeEmailCode_(properties,request,now) {
  // Exact senders are configured from the user's verified portal messages.
  const senders=(properties.getProperty('OTP_SENDERS_'+request.portal.toUpperCase())||'')
    .split(',').map(s=>s.trim().toLowerCase()).filter(s=>bridgeEmails_(s).length===1&&bridgeEmails_(s)[0]===s);
  if (!senders.length) return {code:''};
  const escaped=request.account_email.replace(/["\\]/g,'');
  const query='after:'+Math.floor(request.issued_after_ms/1000)+' to:"'+escaped+'" {'+
    senders.map(s=>'from:'+s).join(' ')+'}';
  const messages=Gmail.Users.Messages.list('me',{q:query,maxResults:20}).messages||[];
  const candidates=[];
  for (const ref of messages.slice(0,20)) {
    const message=Gmail.Users.Messages.get('me',ref.id,{format:'full'}),stamp=Number(message.internalDate);
    if (!Number.isSafeInteger(stamp)||stamp<request.issued_after_ms||stamp>now||now-stamp>300000) continue;
    const headers=(message.payload&&message.payload.headers)||[];
    const header=name=>((headers.find(h=>h.name.toLowerCase()===name.toLowerCase())||{}).value||'');
    const from=bridgeEmails_(header('From')),to=bridgeEmails_(header('To'));
    if (from.length!==1||!senders.includes(from[0])||!to.includes(request.account_email.toLowerCase())) continue;
    const auth=header('Authentication-Results').toLowerCase(),domain=from[0].split('@')[1];
    const escapedDomain=domain.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
    if (!/^\s*mx\.google\.com\s*;/.test(auth)||!/(?:^|[;\s])dmarc=pass(?:[;\s]|$)/.test(auth)||
        !(new RegExp('\\bheader\\.from='+escapedDomain+'(?:[;\\s]|$)')).test(auth)) continue;
    const subject=header('Subject');
    if (!/(?:sign.?in|log.?in|login|security (?:code|verification)|verification code)/i.test(subject)||
        /reset|change.*password|create.*account|job alert|application/i.test(subject)) continue;
    const text=bridgePlainText_(message.payload);
    if (/reset.{0,40}password|password.{0,40}reset|recover.{0,20}account|create.{0,20}account|sign.?up/i.test(text)||
        !/\b(?:sign.?in|log.?in|login|security code|security verification|access your account)\b/i.test(subject+' '+text)) continue;
    const codes=[...new Set([...text.matchAll(/\b(?:code|otp|one[- ]time (?:password|code))\s*(?:is|:|-)?\s*(\d{4,8})\b/gi)].map(m=>m[1]))];
    if(codes.length===1) candidates.push({id:message.id,code:codes[0],issued_at_ms:stamp});
  }
  // Two different fresh login messages are ambiguous, even if their codes match.
  if(candidates.length!==1) return {code:''};
  const chosen=candidates[0],used='otp_used_'+bridgeDigest_(chosen.id);
  const prior=Number(properties.getProperty(used)||0);
  if(prior>now-600000) return {code:''};
  properties.setProperty(used,String(now));
  // Bound persisted one-use markers; they never contain the message or code.
  const all=properties.getProperties();
  Object.keys(all).filter(k=>k.startsWith('otp_used_')&&Number(all[k])<now-600000).slice(0,100)
    .forEach(k=>properties.deleteProperty(k));
  return {code:chosen.code,issued_at_ms:chosen.issued_at_ms};
}
