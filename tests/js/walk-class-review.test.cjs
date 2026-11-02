const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
function fixture() {
  const calls=[];
  const W={urls:{level:'level'},tx:x=>x,post:(url,body)=>new Promise(resolve=>calls.push({body,resolve}))};
  vm.runInNewContext(fs.readFileSync('src/web/static/walk-class-review.js','utf8'),{window:{DecimusWalk:W}});
  const facts={run:'run',edition:'edition',code:'SYN01',zone:'zone-a',words:'Human facts',
    reading:{value:0,confirmed:true,source:'human'},photos:['photo-a'],assigned:true,clarifications:[],search:1};
  const context=()=>({key:JSON.stringify(facts),levels:['D1','D2'],blocked:'',body:{
    run_id:facts.run,checklist_version:facts.edition,code:facts.code,zone:facts.zone,words:facts.words,
    reading_c:facts.reading.confirmed?facts.reading.value:null,photos:facts.photos,clarifications:facts.clarifications}});
  const state=W.classReview.fresh();let active=true;let changes=0;
  const request=(force=false)=>W.classReview.request(state,context(),key=>active && key===context().key,()=>changes++,force);
  async function reply(index=0,extra={}) {
    const {body,resolve}=calls[index];
    resolve({ok:true,body:{...body,status:'ready',level:'D1',need_fact:'',reason:'Criterion',provisional_level:null,
      photo_refs:body.photos,facts_key:'facts',criteria_hash:'criteria',clarification_hash:'chain',
      facts_from:{words:!!body.words.trim(),confirmed_reading:body.reading_c!==null,photos:body.photos.length},...extra}});
    await new Promise(resolve=>setImmediate(resolve));
  }
  return {W,facts,context,state,calls,request,reply,deactivate:()=>active=false};
}
for (const status of ['ready','needs_fact','not_established']) {
  test(`${status} result and pending request are reused only until explicit refresh`,async()=>{
    const f=fixture();f.request();f.request();f.request(true);assert.equal(f.calls.length,1);
    await f.reply(0,status==='needs_fact'?{status,level:null,need_fact:'Which fact?',provisional_level:'D2'}:
      status==='not_established'?{status,level:null,need_fact:null}:{});
    assert.equal(f.state.status,status);
    f.request();f.request();assert.equal(f.calls.length,1);assert.equal(f.state.status,status);
    f.request(true);assert.equal(f.calls.length,2);assert.equal(f.state.status,'pending');
  });
}
const mutations={run:f=>f.run='other',edition:f=>f.edition='other',code:f=>f.code='SYN02',zone:f=>f.zone='zone-b',
  words:f=>f.words='Changed',reading:f=>f.reading.value=5,confirmation:f=>f.reading.confirmed=false,
  source:f=>f.reading.source='model',photos:f=>f.photos=['photo-b'],assignment:f=>f.assigned=false,
  clarifications:f=>f.clarifications=[{question:'Q?',answer:'Human A'}],search:f=>f.search++};
for(const [name,mutate] of Object.entries(mutations)) {
  test(`changed ${name} invalidates settled result and rejects stale pending reply`,async()=>{
    const f=fixture();f.request();await f.reply();mutate(f.facts);f.request();
    assert.equal(f.calls.length,2);assert.equal(f.state.level,null);
    await f.reply(1,{level:'D2'});assert.equal(f.state.level,'D2');
    const g=fixture();g.request();mutate(g.facts);g.request();await g.reply(0);
    assert.equal(g.state.status,'pending');assert.equal(g.state.level,null);
    await g.reply(1,{level:'D2'});assert.equal(g.state.level,'D2');
  });
}
test('manual choice survives identical automatic triggers and a late model reply',async()=>{
  const f=fixture();f.request();f.W.classReview.chooseManual(f.state,f.context(),'D2');
  f.request();await f.reply(0);assert.equal(f.calls.length,1);assert.equal(f.state.level,'D2');assert.equal(f.state.status,'manual');
  f.request(true);assert.equal(f.calls.length,2);await f.reply(1);assert.equal(f.state.level,'D1');
});
test('closed form and separate new form never reuse an earlier result',async()=>{
  const f=fixture();f.request();f.deactivate();await f.reply();assert.equal(f.state.level,null);assert.equal(f.state.status,'idle');
  const g=fixture();g.request();await g.reply();assert.equal(g.calls.length,1);
  const other=g.W.classReview.fresh();g.W.classReview.request(other,g.context(),()=>true,()=>{});
  assert.equal(g.calls.length,2);assert.equal(other.status,'pending');
});

test('answer remains available during explicit checking and a failed request can retry',async()=>{
  const f=fixture();f.state.answer='Human detail';f.request();
  assert.equal(f.state.answer,'Human detail');
  f.calls[0].resolve({ok:false,body:{message:'Unavailable'}});
  await new Promise(resolve=>setImmediate(resolve));assert.equal(f.state.status,'error');
  f.request();assert.equal(f.calls.length,2);assert.equal(f.state.answer,'Human detail');
});

for(const invalid of ['missing','id','revision','scope'])test(`measurement response rejects ${invalid} binding`,async()=>{
  const f=fixture(), c=f.context();c.body.measurement_set_id='a'.repeat(32);c.body.measurement_set_revision='b'.repeat(64);
  c.key=JSON.stringify(c.body);f.W.classReview.request(f.state,c,()=>true,()=>{});
  const measurement={set_id:c.body.measurement_set_id,set_revision:c.body.measurement_set_revision,scope_hash:'c'.repeat(64)};
  if(invalid==='id')measurement.set_id='d'.repeat(32);
  if(invalid==='revision')measurement.set_revision='d'.repeat(64);
  if(invalid==='scope')measurement.scope_hash='';
  await f.reply(0,invalid==='missing'?{}:{measurement_context:measurement});
  assert.equal(f.state.status,'error');assert.equal(f.state.level,null);
});
test('valid measurement binding survives explicit manual override and invalidates with scope',async()=>{
  const f=fixture(), c=f.context();c.body.measurement_set_id='a'.repeat(32);c.body.measurement_set_revision='b'.repeat(64);
  c.key=JSON.stringify(c.body);f.W.classReview.request(f.state,c,()=>true,()=>{});
  const measurement={set_id:c.body.measurement_set_id,set_revision:c.body.measurement_set_revision,scope_hash:'c'.repeat(64)};
  await f.reply(0,{measurement_context:measurement});assert.equal(f.state.status,'ready');
  assert.equal(f.state.measurementContext.scope_hash,measurement.scope_hash);
  f.W.classReview.chooseManual(f.state,c,'D2');assert.equal(f.state.measurementContext.scope_hash,measurement.scope_hash);
  f.W.classReview.sync(f.state,{...c,key:c.key+'new-scope'});
  assert.equal(f.state.measurementContext,null);assert.equal(f.state.level,null);
});
