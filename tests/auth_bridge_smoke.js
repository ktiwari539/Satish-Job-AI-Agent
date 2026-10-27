/* Apps Script logic simulation. No actual Apps Script deployment or Gmail. */
const fs=require('fs'),vm=require('vm'),crypto=require('crypto'),assert=require('assert');
const key='fixture-shared-key-with-at-least-32-characters',email='fixture@example.invalid';
let now=2000000,mail=[],seq=0;
const properties={BRIDGE_SHARED_KEY:key,EMAIL_LINKEDIN:email,PASSWORD_LINKEDIN:'fixture-pass',
  OTP_SENDERS_LINKEDIN:'security@portal.example.invalid'};
const store={getProperty:k=>properties[k]||null,setProperty:(k,v)=>{properties[k]=v;},
  getProperties:()=>({...properties}),deleteProperty:k=>delete properties[k]};
const context={Date:{now:()=>now},ContentService:{MimeType:{JSON:'json'},createTextOutput:value=>({value,setMimeType(){return this;}})},
  PropertiesService:{getScriptProperties:()=>store},LockService:{getScriptLock:()=>({tryLock:()=>true,releaseLock(){}})},
  Utilities:{Charset:{UTF_8:'utf8'},DigestAlgorithm:{SHA_256:'sha256'},
    computeHmacSha256Signature:(message,secret)=>[...crypto.createHmac('sha256',secret).update(message).digest()],
    computeDigest:(_,message)=>[...crypto.createHash('sha256').update(message).digest()],
    base64DecodeWebSafe:s=>Buffer.from(s,'base64url'),newBlob:b=>({getDataAsString:()=>Buffer.from(b).toString('utf8')})},
  Gmail:{Users:{Messages:{list:()=>({messages:mail.map(m=>({id:m.id}))}),get:(_,id)=>mail.find(m=>m.id===id)}}}};
vm.createContext(context);vm.runInContext(fs.readFileSync('apps-script/JobAgentAuthBridge.gs','utf8'),context);
function request(operation='credentials',extra={}) {
  const r={version:1,operation,portal:'linkedin',requested_at_ms:now,nonce:(++seq).toString(16).padStart(32,'0'),
    issued_after_ms:now-10000,account_email:email,...extra};
  const canonical=['version','operation','portal','requested_at_ms','nonce','issued_after_ms','account_email'].map(k=>String(r[k])).join('\n');
  r.signature=crypto.createHmac('sha256',key).update(canonical).digest('hex');return r;
}
function call(r){return JSON.parse(context.doPost({postData:{contents:JSON.stringify(r)}}).value);}
function message(id,overrides={}) {
  return {id,internalDate:String(now-1000),payload:{mimeType:'text/plain',headers:[
    {name:'From',value:'Portal <security@portal.example.invalid>'},{name:'To',value:email},
    {name:'Subject',value:'Your sign-in verification code'},
    {name:'Authentication-Results',value:'mx.google.com; dmarc=pass header.from=portal.example.invalid'}],
    body:{data:Buffer.from('Your verification code is 123456').toString('base64url')}},...overrides};
}
const authenticated=request(); assert.equal(call(authenticated).data.password,'fixture-pass');
assert.equal(call(authenticated).ok,false,'signed request replay rejected');
assert.equal(call({...request(),signature:'0'.repeat(64)}).ok,false,'bad HMAC rejected');
assert.equal(call(request('credentials',{requested_at_ms:now-61000})).ok,false,'stale request rejected');
assert.equal(call(request('credentials',{portal:'unknown'})).ok,false,'unknown portal rejected');
assert.equal(call(request('credentials',{portal:'indeed'})).ok,false,'no implicit password reuse');
properties.SHARED_PORTALS='indeed';properties.SHARED_EMAIL=email;properties.SHARED_PASSWORD='shared-fixture';
assert.equal(call(request('credentials',{portal:'indeed'})).data.password,'shared-fixture','explicit shared account works');
mail=[message('fresh')];let result=call(request('email_otp'));
assert.equal(result.data.code,'123456','authenticated fresh matching login message accepted');
assert.equal(call(request('email_otp')).data.code,'','message cannot be reused');
mail=[message('old',{internalDate:String(now-400000)})];assert.equal(call(request('email_otp')).data.code,'','stale mail rejected');
mail=[message('future',{internalDate:String(now+1000)})];assert.equal(call(request('email_otp')).data.code,'','future mail rejected');
mail=[message('one'),message('two')];assert.equal(call(request('email_otp')).data.code,'','ambiguous mail rejected');
mail=[message('spoof')];mail[0].payload.headers[3].value='mx.google.com; dmarc=fail header.from=portal.example.invalid';
assert.equal(call(request('email_otp')).data.code,'','unauthenticated sender rejected');
mail=[message('wrong-recipient')];mail[0].payload.headers[1].value='other@example.invalid';
assert.equal(call(request('email_otp')).data.code,'','wrong recipient rejected');
mail=[message('reset')];mail[0].payload.headers[2].value='Reset password verification code';
assert.equal(call(request('email_otp')).data.code,'','password reset rejected');
mail=[message('reset-body')];mail[0].payload.headers[2].value='Your verification code';
mail[0].payload.body.data=Buffer.from('To reset your password, code: 123456').toString('base64url');
assert.equal(call(request('email_otp')).data.code,'','password reset in message body rejected');
mail=[message('ambiguous-code')];mail[0].payload.body.data=Buffer.from('Code: 123456. OTP: 654321').toString('base64url');
assert.equal(call(request('email_otp')).data.code,'','multiple codes rejected');
mail=[message('wrong-domain')];mail[0].payload.headers[3].value='mx.google.com; dmarc=pass header.from=portal.example.invalid.evil.invalid';
assert.equal(call(request('email_otp')).data.code,'','lookalike alignment rejected');
assert.equal(call(request('email_otp',{account_email:'other@example.invalid'})).ok,false,'challenge account bound');
assert.equal(JSON.parse(context.doGet().value).ok,false,'GET never releases credentials');
const configRows=[['Control'],[],['Setting','Value','Notes'],['agent_enabled',false],['operating_mode','VALIDATION'],['notice_period_days',30]];
const questionRows=[['Question Pattern','Category','Answer Source','Approved Answer','Auto Answer','Risk Level','Last Reviewed','Notes'],
 ['notice period','Employment','Profile','30 days','YES','LOW','2026-10-27','private note omitted']];
const before=JSON.stringify([configRows,questionRows]);let sheetCall;
properties.CONTROL_SHEET_ID='FIXTURE_CONTROL_ID_WITH_32_CHARACTERS';
context.Sheets={Spreadsheets:{Values:{batchGet:(id,args)=>{sheetCall={id,args};return {valueRanges:[{values:configRows},{values:questionRows}]};}}}};
delete properties.EMAIL_LINKEDIN;delete properties.PASSWORD_LINKEDIN;
const controlRequest=request('control_snapshot',{portal:'control',spreadsheet_id:'untrusted-ignored-id'});
const controlResult=call(controlRequest);
assert.equal(controlResult.ok,true,'control data does not need a portal password');
assert.equal(controlResult.data.question_rows[1][7],'','notes are not exported');
assert.equal(sheetCall.id,properties.CONTROL_SHEET_ID,'only server-configured sheet is read');
assert.deepEqual(Array.from(sheetCall.args.ranges),["'Config'!A1:C200","'Question_Bank'!A1:H1001"],'bounded ranges');
assert.equal(call(controlRequest).ok,false,'control request replay rejected');
assert.equal(call(request('credentials',{portal:'control'})).ok,false,'invalid operation/portal pairing rejected');
assert.equal(JSON.stringify([configRows,questionRows]),before,'source values remain unchanged');
configRows.push(['naukri_password','private-fixture']);
assert.equal(call(request('control_snapshot',{portal:'control'})).ok,false,'credentials are never read from config cells');
configRows.pop();questionRows[1][0]='Portal login password';
assert.equal(call(request('control_snapshot',{portal:'control'})).ok,false,'question bank is not a credential store');
console.log('Apps Script bridge: 20 authentication/mail + 9 control checks passed; no real Gmail/Sheets access.');
