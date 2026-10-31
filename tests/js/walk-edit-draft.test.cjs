const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
function fixture() {
  const storage = new Map();
  const W = {state:{data:{key:'walk_run-a',run_id:'run-a'}},local:{
    get:k=>storage.has(k)?JSON.parse(storage.get(k)):null,
    set:(k,v)=>storage.set(k,JSON.stringify(v)),drop:k=>storage.delete(k)}};
  const context = {window:{DecimusWalk:W,crypto:require('node:crypto').webcrypto},Uint8Array};
  vm.runInNewContext(fs.readFileSync('src/web/static/walk-edit-draft.js','utf8'),context);
  const record={n:1,revision:'a'.repeat(64),photos:[{ref:'old'}]};
  function form(rec=record) {return {source_record:rec,n:1,run_id:'run-a',mode:'violation',code:'CLN05',zone:'hot_kitchen',level:'D1',text:'Server',comment:'',repeat:false,reading:null,photos:rec.photos.map(p=>({...p,state:'done'})),removed:[]};}
  return {W,storage,record,form};
}
test('reload restores explicit edit fields and removals only at same server revision',()=>{
  const {W,record,form}=fixture();let f=form();W.editDraft.init(f,record);
  Object.assign(f,{text:'Human edit',comment:'Human comment',level:'D2',reading:'0',readingSource:'human',readingConfirmed:true,removed:['old']});
  W.editDraft.save(f);f=form();W.editDraft.init(f,record);
  assert.equal(f.text,'Human edit');assert.equal(f.comment,'Human comment');assert.equal(f.level,'D2');assert.equal(f.reading,'0');assert.equal(f.readingConfirmed,true);
  assert.deepEqual(Array.from(f.removed),['old']);assert.equal(f.photos.length,0);
});
test('changed authoritative revision does not silently replace current record',()=>{
  const {W,record,form,storage}=fixture();let f=form();W.editDraft.init(f,record);f.text='Old draft';W.editDraft.save(f);const oldKey=f.draftKey;
  const updated={...record,revision:'b'.repeat(64)};f=form(updated);f.text='New authoritative';W.editDraft.init(f,updated);
  assert.equal(f.text,'New authoritative');assert.equal(f.editRecovery.length,1);assert.equal(f.editRecovery[0].draft.values.text,'Old draft');assert.ok(storage.has(oldKey));
});
test('request ID survives reload/retry and changes when user changes operation',()=>{
  const {W,record,form}=fixture();let f=form();W.editDraft.init(f,record);const a=W.editDraft.body(f,{op:'edit',n:1,text:'After'});
  f=form();W.editDraft.init(f,record);const b=W.editDraft.body(f,{op:'edit',n:1,text:'After'});assert.equal(a.request_id,b.request_id);
  const c=W.editDraft.body(f,{op:'edit',n:1,text:'Changed'});assert.notEqual(c.request_id,b.request_id);assert.equal(c.source_revision,record.revision);
});
test('run and record isolate drafts and stale callback keeps captured old index',()=>{
  const {W,record,form,storage}=fixture();let f=form();W.editDraft.init(f,record);const old=f.draftKey;
  W.state.data={key:'walk_run-b',run_id:'run-b'};f.text='Late captured edit';W.editDraft.save(f);
  assert.ok(storage.has('walk_run-a_edit_index_1'));assert.ok(!storage.has('walk_run-b_edit_index_1'));
  let second=form();second.run_id='run-b';W.editDraft.init(second,record);assert.equal(second.text,'Server');assert.notEqual(second.draftKey,old);
});
test('save preserves unknown receipt metadata, failed submit retains draft, acknowledged save clears only own key',()=>{
  const {W,record,form,storage}=fixture();let f=form();W.editDraft.init(f,record);W.local.set(f.draftKey,{queued:['retained-ref'],other:'preserved'});W.editDraft.save(f);
  assert.equal(W.local.get(f.draftKey).other,'preserved');assert.deepEqual(W.local.get(f.draftKey).queued,['retained-ref']);
  const key=f.draftKey;assert.ok(storage.has(key));W.local.set('unrelated',{safe:true});W.editDraft.clear(f);assert.ok(!storage.has(key));assert.ok(storage.has('unrelated'));
});
test('secondary recovery acknowledges only accepted refs in their original namespace',async()=>{
  const {W,record,form,storage}=fixture();const old='walk_run-a_edit_1_'+'b'.repeat(64);
  let rows=[{id:'receipt-a',key:old,run_id:'run-a',mode:'violation',uploaded_ref:'new-ref'}];
  const calls=[],consumers={};W.offline={
    list:async key=>rows.filter(row=>row.key===key),
    register:(key,consumer)=>{consumers[key]=consumer;return()=>delete consumers[key];},
    ack:async(key,run,ids)=>{calls.push({key,run,ids});rows=rows.filter(row=>row.key!==key||!ids.includes(row.id));return ids.length;},
  };
  const f=form();W.editDraft.init(f,record);f.editRecoveryKeys=[old];W.local.set(old,{source:'kept'});
  W.editDraft.activate(f,()=>{},()=>true);await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.photos.find(p=>p.fresh).ref,'new-ref');assert.ok(storage.has(old));
  await W.editDraft.ack(f,[]);assert.equal(calls.length,0);assert.equal(rows.length,1);
  await W.editDraft.ack(f,['new-ref']);assert.equal(calls[0].key,old);assert.equal(calls[0].run,'run-a');assert.deepEqual(Array.from(calls[0].ids),['receipt-a']);assert.equal(rows.length,0);assert.ok(!storage.has(old));
  W.editDraft.release(f);assert.equal(Object.keys(consumers).length,0);
});
test('late upload consumer never mutates a closed form or a different active run',async()=>{
  const {W,record,form}=fixture();const consumers={};W.offline={list:async()=>[],register:(key,c)=>{consumers[key]=c;return()=>delete consumers[key];}};
  const f=form();W.editDraft.init(f,record);let active=true;W.editDraft.activate(f,()=>{},()=>active);await new Promise(resolve=>setImmediate(resolve));
  const c=consumers[f.draftKey];active=false;assert.equal(c.uploaded({id:'late',key:f.draftKey,run_id:'run-a'},'late-ref'),false);
  active=true;W.state.data.run_id='run-b';assert.equal(c.uploaded({id:'late',key:f.draftKey,run_id:'run-a'},'late-ref'),false);
  assert.equal(f.photos.length,1);
});
test('lost successful edit reload uses server request history, preserving later unsaved human changes',()=>{
  const {W,record,form}=fixture();const first=form();W.editDraft.init(first,record);first.text='After';const body=W.editDraft.body(first,{op:'edit',n:1,text:'After'});
  W.state.data.finding_history=[{kind:'edit',request_id:body.request_id,run_id:'run-a',after:[{n:1,code:'CLN05',level:'D1',zone:'hot_kitchen',text:'After',comment:'',repeat:false,reading_c:null,photos:['old']}]}];
  const updated={...record,revision:'c'.repeat(64)};let fresh=form(updated);fresh.text='After';W.editDraft.init(fresh,updated);
  assert.equal(fresh.editCompleted.length,1);assert.equal(fresh.editRecovery.length,0);
  const old=W.local.get(first.draftKey);old.values.text='Additional unsaved edit';W.local.set(first.draftKey,old);
  fresh=form(updated);W.editDraft.init(fresh,updated);assert.equal(fresh.editCompleted.length,0);assert.equal(fresh.editRecovery.length,1);
});
