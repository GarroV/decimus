const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
function sheet(storage, run = 'run-a') {
  const W = {state: {data: {key: 'key-' + run, legacy_key: 'old', run_id: run}}, local: {
    get: key => storage.get(key), set: (key, value) => storage.set(key, value)
  }, offline: {}};
  let source = fs.readFileSync(path.join(root, 'src/web/static/walk-sheet.js'), 'utf8');
  source = source.replace('W.sheet = {', 'W.test = {loadDraft, saveDraft, setForm: value => { f = value; }}; W.sheet = {');
  vm.runInNewContext(source, {window: {DecimusWalk: W}});
  W.test.setForm({run_id: run, draftKey: 'key-' + run + '_draft', mode: 'violation', words: 'текст', text: '', photos: [], n: null});
  return W;
}
test('draft survives a fresh module, retains words/photos, never moves between runs', () => {
  const storage = new Map();
  let W = sheet(storage);
  W.test.saveDraft();
  W = sheet(storage); // reload
  assert.equal(W.test.loadDraft().words, 'текст');
  assert.equal(W.test.loadDraft().run_id, 'run-a');
  assert.equal(sheet(storage, 'run-b').test.loadDraft(), null);
  assert.equal(storage.get('key-run-a_draft').words, 'текст');
});
test('unknown legacy draft stays recoverable; only matching run migrates', () => {
  const old = {words: 'старый текст', photos: ['photo-old'], mode: 'violation'};
  const storage = new Map([['old_draft', old]]);
  assert.equal(sheet(storage).test.loadDraft(), null);
  assert.equal(storage.get('old_draft'), old);
  old.run_id = 'run-a';
  assert.equal(sheet(storage).test.loadDraft().photos[0], 'photo-old');
  assert.equal(storage.get('old_draft'), old);
});
function offline(records, run = 'run-a', storage = new Map()) {
  let uploads = 0;
  const navigator = {onLine:true}; const timers=[];
  const W = {state: {data: {key: 'key-' + run, run_id: run}}, local: {
    get: key => storage.get(key), set: (key, value) => storage.set(key, value)
  }, photo: {upload: async () => { uploads++; return 'uploaded'; }}, toast() {}, tx() {}};
  const db = {transaction() {
    const tx = {objectStore() { return {
      getAll() { const req = {result: records.slice()}; queueMicrotask(() => tx.oncomplete()); return req; },
      add(row) { records.push(row); queueMicrotask(() => tx.oncomplete()); return {result:row.id}; },
      put(row) {
        const at = records.findIndex(r => r.id === row.id);
        if (at === -1) records.push(row); else records[at] = row;
        queueMicrotask(() => tx.oncomplete()); return {result: row.id};
      },
      delete(id) { records.splice(records.findIndex(r => r.id === id), 1); queueMicrotask(() => tx.oncomplete()); return {}; }
    }; }}; return tx;
  }};
  const indexedDB = {open() {const req = {result: db}; queueMicrotask(() => req.onsuccess()); return req; }};
  vm.runInNewContext(fs.readFileSync(path.join(root, 'src/web/static/walk-offline.js'), 'utf8'), {
    window: {DecimusWalk: W, indexedDB, addEventListener() {}}, document: {addEventListener() {}},
    navigator, Blob,
    FileReader: class {readAsArrayBuffer(blob) {blob.arrayBuffer().then(bytes=>{this.result=bytes;this.onload();});}},
    setTimeout(callback,ms) {timers.push({callback,ms});return timers.length;}, clearTimeout() {}, Date, Promise
  });
  return {W, storage, navigator, timers, uploads: () => uploads};
}
test('offline flush uploads only current run; unknown and other run photos survive', async () => {
  const frame = (id, run_id) => ({id, run_id, key: 'key-' + run_id + '_draft', mode: 'violation', at: Date.now(), bytes: new ArrayBuffer(1)});
  const records = [frame('a', 'run-a'), frame('b', 'run-b'), {...frame('legacy', undefined), key: 'old_draft'}];
  const env = offline(records);
  await env.W.offline.kick();
  assert.equal(env.uploads(), 1);
  assert.deepEqual(records.map(r => r.id), ['b', 'legacy']);
  assert.equal(env.storage.get('key-run-a_draft').run_id, 'run-a');
  assert.equal(env.storage.get('key-run-a_draft').photos[0], 'uploaded');
});
test('stale upload conflict retains original bytes and permits a later retry once', async () => {
  const records = [{id:'a', run_id:'run-a', key:'key-run-a_draft', mode:'violation', at:Date.now(), bytes:new ArrayBuffer(5)}];
  const env = offline(records);
  env.W.photo.upload = async () => { throw {status:409, code:'run_changed', retryable:false}; };
  await env.W.offline.kick();
  assert.equal(records.length, 1);
  assert.equal(records[0].bytes.byteLength, 5);
  let uploads = 0;
  env.W.photo.upload = async (blob, runId) => {uploads++; assert.equal(runId,'run-a'); return 'retry-photo';};
  await env.W.offline.kick();
  await env.W.offline.kick();
  assert.equal(uploads, 1);
  assert.equal(records.length, 0);
  assert.equal(env.storage.get('key-run-a_draft').photos[0], 'retry-photo');
});
function infoFrame(id, code = 'INF01', run = 'run-a') {
  return {id, run_id:run, key:'key-' + run + '_info_' + code, mode:'info', at:Date.now(), bytes:new ArrayBuffer(7)};
}
test('registered info consumer receives only its own key; closed fields persist separately', async () => {
  const records = [infoFrame('a'), infoFrame('b','INF02'), infoFrame('foreign','INF01','run-b'),
    {...infoFrame('unknown'), key:'key-run-a_finish_run-a', at:0}];
  const env = offline(records);
  const calls = [];
  env.W.offline.onUploaded = () => {throw new Error('info leaked into finding consumer');};
  const unregister = env.W.offline.register('key-run-a_info_INF01', {
    uploaded(entry, ref) {calls.push([entry.key,entry.run_id,ref]); return true;}
  });
  await env.W.offline.kick();
  assert.equal(calls.length,1);
  assert.deepEqual(calls[0],['key-run-a_info_INF01','run-a','uploaded']);
  assert.equal(env.storage.get('key-run-a_info_INF02').photos[0],'uploaded');
  assert.equal(records.length,2);
  assert.deepEqual(records.map(r=>r.id),['foreign','unknown']);
  unregister();
});
test('successful info upload preserves original bytes until verified local persistence, reload avoids reupload', async () => {
  const records = [infoFrame('a')];
  const env = offline(records);
  env.W.local.set = () => {}; // device storage full
  await env.W.offline.kick();
  assert.equal(env.uploads(),1);
  assert.equal(records.length,1);
  assert.equal(records[0].bytes.byteLength,7);
  assert.equal(records[0].uploaded_ref,'uploaded');
  const reloaded = offline(records); // new module, same durable IDB rows
  await reloaded.W.offline.kick();
  await reloaded.W.offline.kick();
  assert.equal(reloaded.uploads(),0);
  assert.equal(records.length,0);
  assert.equal(reloaded.storage.get('key-run-a_info_INF01').photos.length,1);
});
test('unregistered info consumer falls back to durable merge, preserving other payload properties', async () => {
  const records = [infoFrame('a')];
  const env = offline(records);
  const original = {run_id:'run-a',photos:['already'],queued:['already'],other:'kept'};
  env.storage.set('key-run-a_info_INF01', original);
  const unregister = env.W.offline.register('key-run-a_info_INF01', () => {throw new Error('unregistered');});
  unregister();
  await env.W.offline.kick();
  const draft = env.storage.get('key-run-a_info_INF01');
  assert.equal(draft.other,'kept');
  assert.equal(draft.photos.filter(ref=>ref==='uploaded').length,1);
  assert.equal(records.length,0);
});
test('info network failure keeps original blob; retry appends exactly once', async () => {
  const records = [infoFrame('a')];
  const env = offline(records);
  let calls=0;
  env.W.photo.upload = async () => {if (++calls === 1) throw {retryable:true}; return 'later';};
  await env.W.offline.kick();
  assert.equal(records.length,1);
  assert.equal(records[0].bytes.byteLength,7);
  assert.equal(records[0].uploaded_ref,undefined);
  await env.W.offline.kick();await env.W.offline.kick();
  assert.equal(calls,2);
  assert.equal(env.storage.get('key-run-a_info_INF01').photos.filter(ref=>ref==='later').length,1);
});
test('in-flight old info upload settles only into original key after active run changes', async () => {
  const records = [infoFrame('a')];
  const env = offline(records);
  let adopted=0;
  env.W.offline.register('key-run-a_info_INF01',()=>{adopted++;return true;});
  env.W.photo.upload=async () => {
    env.W.state.data={key:'key-run-b',run_id:'run-b'};
    return 'old-completed';
  };
  await env.W.offline.kick();
  assert.equal(adopted,0);
  assert.equal(env.storage.get('key-run-a_info_INF01').run_id,'run-a');
  assert.equal(env.storage.get('key-run-a_info_INF01').photos[0],'old-completed');
  assert.equal(env.storage.has('key-run-b_info_INF01'),false);
});
test('a seal conflict also keeps pending bytes if a concurrent replacement hid the run error', async () => {
  const records = [infoFrame('a')];
  const env = offline(records);
  env.W.photo.upload=async()=>{throw {status:409,retryable:false};};
  await env.W.offline.kick();
  assert.equal(records.length,1);
  assert.equal(records[0].bytes.byteLength,7);
});
test('enqueue during a pending upload coalesces a second pass without waiting for online', async () => {
  const records=[infoFrame('first')];const env=offline(records);
  let release;let calls=0;
  env.W.photo.upload=async()=>{calls++;if(calls===1)return new Promise(resolve=>{release=resolve;});return 'second-ref';};
  const running=env.W.offline.kick();
  while(!release)await new Promise(setImmediate);
  await env.W.offline.put('key-run-a_info_INF01','info',new Blob(['second-frame']),'run-a');
  await env.W.offline.kick();env.W.offline.watch();
  release('first-ref');await running;
  assert.equal(records.length,0);
  assert.equal(calls,2);
  assert.deepEqual(Array.from(env.storage.get('key-run-a_info_INF01').photos),['first-ref','second-ref']);
});
test('a busy enqueue followed by offline schedules a bounded retry and keeps the second blob', async () => {
  const records=[infoFrame('first')];const env=offline(records);
  let release;let calls=0;
  env.W.photo.upload=async()=>{calls++;return new Promise(resolve=>{release=resolve;});};
  const running=env.W.offline.kick();
  while(!release)await new Promise(setImmediate);
  await env.W.offline.put('key-run-a_info_INF01','info',new Blob(['second-frame']),'run-a');
  env.navigator.onLine=false;
  await env.W.offline.kick();env.W.offline.watch();
  release('first-ref');await running;
  assert.equal(calls,1);
  assert.equal(records.length,1);
  assert.equal(records[0].bytes.byteLength,12);
  assert.equal(env.timers.length,1);
});
