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
function offline(records, run = 'run-a') {
  const storage = new Map(); let uploads = 0;
  const W = {state: {data: {key: 'key-' + run, run_id: run}}, local: {
    get: key => storage.get(key), set: (key, value) => storage.set(key, value)
  }, photo: {upload: async () => { uploads++; return 'uploaded'; }}, toast() {}, tx() {}};
  const db = {transaction() {
    const tx = {objectStore() { return {
      getAll() { const req = {result: records.slice()}; queueMicrotask(() => tx.oncomplete()); return req; },
      delete(id) { records.splice(records.findIndex(r => r.id === id), 1); queueMicrotask(() => tx.oncomplete()); return {}; }
    }; }}; return tx;
  }};
  const indexedDB = {open() {const req = {result: db}; queueMicrotask(() => req.onsuccess()); return req; }};
  vm.runInNewContext(fs.readFileSync(path.join(root, 'src/web/static/walk-offline.js'), 'utf8'), {
    window: {DecimusWalk: W, indexedDB, addEventListener() {}}, document: {addEventListener() {}},
    navigator: {onLine: true}, Blob, setTimeout() {}, clearTimeout() {}, Date, Promise
  });
  return {W, storage, uploads: () => uploads};
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
