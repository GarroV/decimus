const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function fixture() {
  const revision='a'.repeat(64), stored=new Map();
  const source=(n,zone,extra={})=>({n,zone,level:'D0',reading_c:6,revision,...extra});
  const group={schema:1,id:'a'.repeat(32),revision,code:'SYN01',zone:'zone-a',line_label:'Synthetic line',
    confirmed:true,stale:false,products:[{id:'b'.repeat(32),label:'Synthetic product',facts:'Synthetic time/category',
      confirmed_product:true,sources:[{n:1,revision},{n:2,revision}]}]};
  const W={state:{data:{run_id:'run-a',measurement_sets:[group],zones:[
    {code:'zone-a',recorded:[source(1,'zone-a'),source(2,'zone-a'),source(4,'zone-a',{level:'D1'}),source(5,'zone-a',{reading_c:null})]},
    {code:'zone-b',recorded:[source(3,'zone-b')]}]}},
    local:{get:k=>stored.has(k)?JSON.parse(stored.get(k)):null,set:(k,v)=>stored.set(k,JSON.stringify(v))}};
  vm.runInNewContext(fs.readFileSync('src/web/static/walk-measurement-sets.js','utf8'),{window:{DecimusWalk:W}});
  const form={run_id:'run-a',run_key:'key-a'};
  const slot=W.measurementSets.slot(form,'SYN01','zone-a');slot.selected=group.id;
  return {W,form,slot,group,source,stored,revision,context:()=>W.measurementSets.context(form,'SYN01','zone-a')};
}
test('sources are saved numeric D0 in the same physical zone, excluding current target',()=>{
  const f=fixture();assert.deepEqual(Array.from(f.W.measurementSets.sources('zone-a'),r=>r.n),[1,2]);
  assert.deepEqual(Array.from(f.W.measurementSets.sources('zone-a',1),r=>r.n),[2]);
});
test('repeat readings retain one explicitly confirmed product and refs cannot count twice',()=>{
  const f=fixture(), draft=structuredClone(f.group), available=f.W.measurementSets.sources('zone-a');
  assert.equal(f.W.measurementSets.validate(draft,available),'');assert.equal(draft.products.length,1);
  draft.products.push({...structuredClone(draft.products[0]),id:'c'.repeat(32)});
  assert.equal(f.W.measurementSets.validate(draft,available),'walk.measurement.duplicate');
});
for(const field of ['confirmed','confirmed_product','sources','label','line_label'])test(`explicit ${field} is required`,()=>{
  const f=fixture(), draft=structuredClone(f.group);
  if(field==='confirmed')draft.confirmed=false;
  else if(field==='line_label')draft.line_label='';
  else draft.products[0][field]=field==='sources'?[]:field==='label'?'':false;
  assert.equal(f.W.measurementSets.validate(draft,f.W.measurementSets.sources('zone-a')),'walk.measurement.confirm');
});
test('stale ref is refused without silently adopting the current source revision',()=>{
  const f=fixture();f.W.state.data.zones[0].recorded[0].revision='b'.repeat(64);
  assert.equal(f.W.measurementSets.validate(f.group,f.W.measurementSets.sources('zone-a')),'walk.measurement.stale');
  assert.equal(f.group.products[0].sources[0].revision,f.revision);
});
for(const change of ['selected','other_line','source','inventory'])test(`scope key invalidates on ${change}`,()=>{
  const f=fixture(), before=f.context().key;
  if(change==='selected')f.group.revision='b'.repeat(64);
  if(change==='other_line')f.W.state.data.measurement_sets.push({...f.group,id:'d'.repeat(32)});
  if(change==='source')f.W.state.data.zones[0].recorded[0].revision='b'.repeat(64);
  if(change==='inventory')f.W.state.data.zones[0].recorded.push(f.source(6,'zone-a'));
  assert.notEqual(f.context().key,before);
});
test('unrelated zones and criteria do not contaminate the scope key',()=>{
  const f=fixture(), before=f.context().key;
  f.W.state.data.zones[1].recorded[0].revision='b'.repeat(64);
  f.W.state.data.measurement_sets.push({...f.group,id:'c'.repeat(32),code:'SYN02'});
  assert.equal(f.context().key,before);
});
test('missing/stale groups block classification and unsaved line edits never appear as saved facts',()=>{
  const f=fixture();f.group.stale=true;assert.equal(f.context().blocked,'walk.measurement.stale');
  f.group.stale=false;f.slot.draft={...f.group,id:'c'.repeat(32)};f.slot.dirty=true;
  assert.equal(f.context().blocked,'walk.measurement.unsaved');
  f.slot.dirty=false;f.W.state.data.measurement_sets=[];assert.equal(f.context().blocked,'walk.measurement.stale');
});
test('per-run draft namespace never imports another inspection',()=>{
  const f=fixture();f.stored.set(f.slot.localKey,JSON.stringify({...f.slot,run_id:'other-run',draft:{line_label:'Other'}}));
  const newForm={run_id:'run-a',run_key:'key-a'};
  assert.equal(f.W.measurementSets.slot(newForm,'SYN01','zone-a').draft,null);
  assert.equal(f.W.measurementSets.slot(newForm,'SYN01','zone-b').draft,null);
});
