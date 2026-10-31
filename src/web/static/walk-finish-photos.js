/* Фотоответы к реальным field.code: существующая камера/загрузка + общая
 * долговечная очередь. Подтверждённые кадры здесь только читаются.
 */
(function () {
  "use strict";
  var W = window.DecimusWalk;
  var context = null;
  var fields = {};
  var seq = 0;
  function tx(key) { return W.tx("walk.finish.photos." + key); }
  function photoKey(code) { return context.key + "_info_" + code; }
  function detach() {
    Object.keys(fields).forEach(function (code) { if (fields[code].unregister) fields[code].unregister(); });
  }
  function arrived(state, entry, ref) {
    if (state.cancelled && state.cancelled[entry.id]) { ack(state.code, [ref], [entry.id]); return true; }
    if ((state.field.photos || []).some(function (p) { return p.ref === ref; })) { ack(state.code, [ref], [entry.id]); return true; }
    var exact = state.items.filter(function (p) { return p.entryId === entry.id; })[0];
    var existing = state.items.filter(function (p) { return p.ref === ref; })[0];
    if (exact && existing && exact !== existing) {
      state.items = state.items.filter(function (p) { return p !== exact; });
      if (exact.url) URL.revokeObjectURL(exact.url);
    }
    var p = existing || exact;
    if (!p) { p = { id: ++seq, own: true }; state.items.push(p); }
    p.receiptIds = (p.receiptIds || []).concat(exact && exact.receiptIds || [], [entry.id]).filter(function (id, at, all) { return all.indexOf(id) === at; });
    if (!p.url && entry.blob) p.url = URL.createObjectURL(entry.blob);
    p.ref = ref; p.state = "done"; p.entryId = entry.id;
    p.file = null; p.blob = null;
    draw(state);
    return true;
  }
  function start(data) {
    detach();
    if (!context || context.run !== data.run_id || context.key !== data.key) {
      Object.keys(fields).forEach(function (code) { fields[code].items.forEach(function (p) { if (p.url) URL.revokeObjectURL(p.url); }); });
      fields = {};
    }
    context = { key: data.key, run: data.run_id };
    return Promise.all((data.info || []).map(function (field) {
      var state = fields[field.code] || { code: field.code, items: [], cancelled: {} };
      fields[field.code] = state; state.field = field;
      var confirmed = (field.photos || []).map(function (p) { return p.ref; });
      state.items = state.items.filter(function (p) { return !p.ref || confirmed.indexOf(p.ref) === -1; });
      var draft = W.local.get(photoKey(field.code));
      if (draft && draft.run_id === context.run) (draft.photos || []).forEach(function (ref) {
        if (confirmed.indexOf(ref) === -1 && !state.items.some(function (p) { return p.ref === ref; })) state.items.push({ id: ++seq, ref: ref, own: true, state: "done" });
      });
      if (!(W.offline && W.offline.register)) return;
      state.unregister = W.offline.register(photoKey(field.code), {
        uploaded: function (entry, ref) { return arrived(state, entry, ref); },
        failed: function (entry) {
          var p = state.items.filter(function (p) { return p.entryId === entry.id; })[0];
          if (p) { p.state = "failed"; p.error = W.tx("walk.err.photo_bad"); changed(state); }
        },
      });
      return W.offline.list(photoKey(field.code)).then(function (entries) {
        entries.forEach(function (entry) {
          if (entry.uploaded_ref) { arrived(state, entry, entry.uploaded_ref); return; }
          if (!state.items.some(function (p) { return p.entryId === entry.id; })) state.items.push({ id: ++seq, entryId: entry.id, receiptIds: [entry.id], blob: entry.blob, url: URL.createObjectURL(entry.blob), own: true, state: entry.upload_error ? "failed" : "waiting", error: entry.upload_error ? W.tx("walk.err.photo_bad") : null });
        });
        draw(state);
      });
    }));
  }
  function changed(state) {
    draw(state);
    if (state.onChange) state.onChange();
  }
  function queue(state, p) {
    p.state = "uploading"; changed(state);
    var run = context.run;
    var k = photoKey(state.code);
    if (p.entryId && W.offline.retry) {
      W.offline.retry(p.entryId, k, run).then(function () {
        p.state = "waiting"; changed(state); W.offline.kick(); W.offline.watch();
      });
      return;
    }
    var compressed = p.blob ? Promise.resolve(p.blob) : W.photo.compress(p.file);
    compressed.then(function (blob) {
      if (p.cancelled) return null;
      p.blob = blob;
      p.file = null;
      if (p.url) URL.revokeObjectURL(p.url);
      p.url = URL.createObjectURL(blob);
      if (!W.offline || !W.offline.available() || !W.offline.register) {
        var unavailable = new Error("storage"); unavailable.reason = "unavailable"; throw unavailable;
      }
      return W.offline.put(k, "info", blob, run);
    }).then(function (entry) {
      if (!entry) return;
      if (p.cancelled) { state.cancelled[entry.id] = true; W.offline.remove(entry.id); return; }
      p.entryId = entry.id; p.receiptIds = [entry.id]; p.state = "waiting"; changed(state);
      W.offline.kick().then(function () {
        if (p.state === "done") return;
        return W.offline.list(k).then(function (rows) {
          if (!rows.some(function (entry) { return entry.id === p.entryId; }) && !p.ref) {
            p.state = "failed"; p.error = W.tx("walk.err.photo_bad"); changed(state);
          }
        });
      });
      W.offline.watch();
    }).catch(function (err) {
      if (p.cancelled) return;
      p.state = "failed";
      p.error = err && err.reason === "full" ? W.tx("walk.offline.full") :
        err && err.reason === "unavailable" ? tx("no_storage") : W.tx("walk.err.photo_bad");
      W.toast(p.error, "warn");
      changed(state);
    });
  }
  function forget(state, p) {
    var capturedKey = photoKey(state.code); var capturedRun = context.run;
    p.cancelled = true;
    var ids = p.receiptIds || (p.entryId ? [p.entryId] : []);
    ids.forEach(function (id) { state.cancelled[id] = true; });
    function remove() {
      state.items = state.items.filter(function (q) { return q !== p; });
      if (p.url) URL.revokeObjectURL(p.url);
      if (p.ref) {
        var k = capturedKey; var draft = W.local.get(k);
        if (draft && draft.run_id === capturedRun) {
          draft.photos = (draft.photos || []).filter(function (ref) { return ref !== p.ref; });
          draft.queued = (draft.queued || []).filter(function (ref) { return ref !== p.ref; });
          W.local.set(k, draft);
        }
      }
      changed(state);
    }
    if (ids.length && W.offline) Promise.all(ids.map(function (id) { return W.offline.remove(id); })).then(remove, function () {
      p.cancelled = false; ids.forEach(function (id) { delete state.cancelled[id]; });
      p.state = "failed"; p.error = tx("no_storage"); changed(state);
    }); else remove();
  }
  function draw(state) {
    if (!state.box || !state.box.isConnected) return;
    var box = state.box; box.textContent = "";
    box.appendChild(W.el("p", "walk-form__hint", tx("hint")));
    var strip = W.el("div", "walk-strip");
    (state.field.photos || []).forEach(function (p) {
      var cell = W.el("div", "walk-strip__cell"); cell.appendChild(W.photo.thumb(p)); strip.appendChild(cell);
    });
    (state.readOnly ? [] : state.items).forEach(function (p) {
      var cell = W.el("div", "walk-strip__cell is-" + p.state);
      cell.appendChild(W.photo.thumb(p));
      if (p.state !== "done") cell.appendChild(W.el("span", "walk-strip__state", p.state === "failed" ? tx("failed") : W.tx("walk.photo." + (p.state === "waiting" ? "waiting" : "uploading"))));
      if (p.state === "failed") {
        cell.appendChild(W.button("walk-strip__retry", W.tx("walk.photo.failed"), function () { queue(state, p); }));
        cell.title = p.error || "";
      }
      var x = W.button("walk-strip__remove", "✕", function () { forget(state, p); });
      x.setAttribute("aria-label", W.tx("walk.photo.remove")); cell.appendChild(x); strip.appendChild(cell);
    });
    box.appendChild(strip);
    var failed = state.items.filter(function (p) { return p.state === "failed" && p.error; });
    if (failed.length && !state.readOnly) box.appendChild(W.el("p", "walk-form__note", failed[0].error));
    if (state.readOnly) return;
    box.appendChild(W.photo.picker(tx("add"), function (files) {
      files.forEach(function (file) {
        var p = { id: ++seq, file: file, own: true, url: URL.createObjectURL(file), state: "uploading" };
        state.items.push(p); queue(state, p);
      });
    }, false));
  }
  function render(field, readOnly) {
    var state = fields[field.code];
    state.readOnly = !!readOnly;
    state.field = field; state.box = W.el("div", "walk-finish-photos");
    // Draw after insertion as draw deliberately does not update detached old forms.
    window.requestAnimationFrame(function () { draw(state); });
    return state.box;
  }
  function refs(code) { return fields[code] ? fields[code].items.filter(function (p) { return p.ref && p.state === "done"; }).map(function (p) { return p.ref; }) : []; }
  function hasNew(code) { return !!fields[code] && fields[code].items.length > 0; }
  function pending() { return Object.keys(fields).some(function (code) { return fields[code].items.some(function (p) { return p.state !== "done"; }); }); }
  function ack(code, saved, extraIds) {
    var state = fields[code]; if (!state) return Promise.resolve();
    var ids = extraIds || [];
    state.items.forEach(function (p) { if (saved.indexOf(p.ref) !== -1) ids = ids.concat(p.receiptIds || (p.entryId ? [p.entryId] : [])); });
    var k = photoKey(code); var draft = W.local.get(k);
    var run = context.run;
    function cleanup() {
      state.items = state.items.filter(function (p) {
        if (saved.indexOf(p.ref) === -1) return true;
        if (p.url) URL.revokeObjectURL(p.url);
        return false;
      });
      draft = W.local.get(k);
      if (draft && draft.run_id === run) {
        draft.photos = (draft.photos || []).filter(function (ref) { return saved.indexOf(ref) === -1; });
        draft.queued = (draft.queued || []).filter(function (ref) { return saved.indexOf(ref) === -1; });
        W.local.set(k, draft);
      }
    }
    return W.offline.ack(k, run, ids).then(cleanup, cleanup);
  }
  W.finish.photos = { start: start, render: render, refs: refs, hasNew: hasNew, pending: pending, ack: ack, detach: detach };
})();
