const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
function core() {
  const sent = [];
  const window = {};
  vm.runInNewContext(fs.readFileSync(path.join(root, 'src/web/static/walk-core.js'), 'utf8'), {
    window,
    document: {getElementById: () => ({getAttribute: name => name})},
    fetch: async (url, options) => {sent.push({url, options}); return {
      ok: true, status: 200, headers: {get: () => 'application/json'}, json: async () => ({})
    };}
  });
  const W = window.DecimusWalk;
  W.state.data = {run_id: 'new-run'};
  return {W, sent};
}
test('JSON mutations use captured identity and preserve explicit payload identity', async () => {
  const {W, sent} = core();
  const original = {value: 'old text'};
  await W.api.write(W.urls.info, original, 'old-run');
  assert.equal(JSON.parse(sent[0].options.body).run_id, 'old-run');
  assert.equal(original.run_id, undefined);
  await W.api.write(W.urls.finding, {op: 'drop', n: 1, run_id: 'old-run'});
  assert.equal(JSON.parse(sent[1].options.body).run_id, 'old-run');
});
test('raw photo carries captured header; start/preferences and W.post remain compatible', async () => {
  const {W, sent} = core();
  const bytes = new Uint8Array([1, 2]);
  await W.api.write(W.urls.photo, bytes, 'old-run', 'image/jpeg');
  assert.equal(sent[0].options.headers['X-Walk-Run-Id'], 'old-run');
  assert.equal(sent[0].options.body, bytes);
  await W.api.write(W.urls.start, {op: 'start'}, 'old-run');
  await W.api.write(W.urls.app, {lang: 'en'}, 'old-run');
  await W.post(W.urls.info, {value: 'legacy'});
  for (const row of sent.slice(1)) {
    assert.equal(row.options.headers['X-Walk-Run-Id'], undefined);
    assert.equal(JSON.parse(row.options.body).run_id, undefined);
  }
});
