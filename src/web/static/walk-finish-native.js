/* Завершение целиком в miniapp: сведения → предвычитка → явная сдача.
 * Отчёт/печать/архив по-прежнему делает общий deliver. Старое подтверждение
 * остаётся только явно выбранным запасным выходом в чат.
 */
(function () {
  "use strict";
  var W = window.DecimusWalk;
  var chatAsk = W.finish.ask;
  var el = W.el;
  var view = null;
  var poll = null;
  var flow = null;

  function data() { return W.state.data || {}; }
  function tx(key, args) { return W.tx("walk.finish.native." + key, args); }
  function key() { return flow.key + "_finish_" + flow.run; }
  function keep() { W.local.set(key(), { run_id: flow.run, fields: flow.fields }); }
  function current() { return flow && data().run_id === flow.run; }
  function close() {
    if (flow && flow.busy) return;
    if (poll) window.clearTimeout(poll);
    poll = null;
    if (view) view.remove();
    view = null;
    document.removeEventListener("keydown", onKey);
  }
  function onKey(e) { if (e.key === "Escape" && !flow.busy) close(); }
  function error(err) {
    if (!view) return;
    var note = view.querySelector(".walk-finish__error");
    note.textContent = err && err.message && err.message !== "Failed to fetch" ? err.message : W.tx("walk.err.network");
  }
  function post(body) {
    return W.post(W.urls.app, body).then(function (res) {
      if (!res.ok) throw new Error(res.body && res.body.message || W.tx("walk.error"));
      return res.body;
    });
  }
  function button(label, action, quiet) {
    return W.button(quiet ? "walk-link" : "walk-mark", label, action);
  }
  function frame(title) {
    if (view) view.remove();
    view = el("section", "walk-sheet walk-finish");
    view.id = "walk-confirm";
    view.setAttribute("role", "dialog");
    view.setAttribute("aria-modal", "true");
    view.setAttribute("aria-label", title);
    var head = el("header", "walk-sheet__head");
    head.appendChild(el("h2", "walk-sheet__title", title));
    var x = button(W.tx("walk.sheet.close"), close, true);
    x.disabled = flow.busy;
    head.appendChild(x);
    view.appendChild(head);
    var body = el("div", "walk-sheet__body walk-finish__body");
    body.appendChild(el("p", "walk-finish__meta", (data().unit || "") + " · " + W.day(data().date)));
    var err = el("p", "walk-finish__error");
    err.setAttribute("role", "alert");
    body.appendChild(err);
    view.appendChild(body);
    document.body.appendChild(view);
    document.addEventListener("keydown", onKey);
    return body;
  }
  function loading() { frame(W.tx("walk.finish.title")).appendChild(el("p", null, tx("loading"))); }
  function apply(body) { if (body && W.apply) W.apply(body); }
  function fetchReview() {
    if (!current()) return Promise.reject(new Error(W.tx("walk.finish.err.stale")));
    var mine = flow;
    return post({ op: "finish_review" }).then(function (review) {
      if (flow !== mine || !view) throw new Error(W.tx("walk.sheet.cancel"));
      if (review.run_id !== flow.run) throw new Error(W.tx("walk.finish.err.stale"));
      flow.review = review;
      apply(review.data);
      return review;
    });
  }
  function iso(value) {
    var m = /^(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{2}):(\d{2}))?$/.exec(value || "");
    return m ? m[3] + "-" + m[2] + "-" + m[1] + (m[4] ? "T" + m[4] + ":" + m[5] : "") : "";
  }
  function input(field) {
    var node;
    if (field.kind === "yes_no") {
      node = el("select", "walk-input");
      [["", tx("skip")], ["yes", W.tx("walk.info.yes")], ["no", W.tx("walk.info.no")]].forEach(function (pair) {
        var option = el("option", null, pair[1]); option.value = pair[0]; node.appendChild(option);
      });
      node.value = /^(yes|да)$/i.test(field.value) ? "yes" : /^(no|нет)$/i.test(field.value) ? "no" : "";
    } else if (field.kind === "date") {
      node = el("input", "walk-input");
      node.type = field.code === "INF05" ? "datetime-local" : "date";
      node.value = iso(field.value);
    } else {
      node = el("textarea", "walk-area"); node.rows = 3; node.maxLength = 1000; node.value = field.value || "";
    }
    if (Object.prototype.hasOwnProperty.call(flow.fields, field.code)) node.value = flow.fields[field.code];
    node.id = "finish-field-" + field.code;
    node.addEventListener("input", function () { flow.fields[field.code] = node.value; keep(); });
    node.addEventListener("change", function () { flow.fields[field.code] = node.value; keep(); });
    return node;
  }
  function info() {
    if (!view) return;
    var body = frame(tx("details"));
    body.appendChild(el("p", "walk-form__hint", tx("optional")));
    (data().info || []).forEach(function (field) {
      var row = el("section", "walk-finish__field");
      var label = el("label", "walk-form__label", field.q);
      var area = input(field); label.htmlFor = area.id;
      row.appendChild(label); row.appendChild(area);
      if (field.value) row.appendChild(el("p", "walk-form__hint", tx("saved", { value: field.value })));
      body.appendChild(row);
    });
    var next = button(tx("review"), function () { saveDetails(next); });
    body.appendChild(next);
    body.appendChild(button(tx("chat"), function () { close(); chatAsk(); }, true));
  }
  function saveDetails(next) {
    if (flow.busy) return;
    flow.busy = true; next.disabled = true;
    var fields = (data().info || []).filter(function (f) {
      return Object.prototype.hasOwnProperty.call(flow.fields, f.code) && flow.fields[f.code].trim();
    });
    var chain = Promise.resolve();
    fields.forEach(function (field) {
      chain = chain.then(function () {
        if (!current()) throw new Error(W.tx("walk.finish.err.stale"));
        return W.post(W.urls.info, { code: field.code, value: flow.fields[field.code], run_id: flow.run }).then(function (res) {
          if (!res.ok) throw new Error(res.body && res.body.message || W.tx("walk.error"));
          delete flow.fields[field.code]; keep(); apply(res.body);
        });
      });
    });
    chain.then(fetchReview).then(function () { flow.busy = false; summary(); }).catch(function (err) {
      flow.busy = false; next.disabled = false; error(err);
    });
  }
  function edit(record, zone) {
    close();
    W.sheet.open(record ? { record: record, zone: zone } : { mode: "advice", zone: zone });
    function resume() {
      if (W.sheet.isOpen()) { poll = window.setTimeout(resume, 250); return; }
      if (!current()) return;
      loading(); fetchReview().then(summary).catch(error);
    }
    poll = window.setTimeout(resume, 250);
  }
  function summary() {
    if (!view) return;
    var review = flow.review;
    var body = frame(tx("review"));
    var score = review.summary;
    body.appendChild(el("p", "walk-finish__score", String(score.pct) + "% · " + score.grade + " · " + score.label));
    body.appendChild(el("p", "walk-form__hint", tx("records", { count: score.total })));
    Object.keys(score.counts || {}).forEach(function (level) {
      body.appendChild(el("span", "walk-finish__count", level + ": " + score.counts[level]));
    });
    (data().zones || []).forEach(function (zone) {
      if (!zone.recorded.length) return;
      body.appendChild(el("h3", null, zone.title));
      zone.recorded.forEach(function (record) {
        var kind = record.level === "R" ? "advice" : record.level === "D0" ? "info" : "violation";
        var row = el("div", "walk-finish__record");
        row.appendChild(el("span", "walk-item-kind walk-item-kind--" + kind, W.tx("walk.item.kind." + kind)));
        row.appendChild(el("p", null, record.text));
        if (record.comment) row.appendChild(el("p", "walk-form__hint", record.comment));
        row.appendChild(button(W.tx("walk.sheet.change"), function () { edit(record, zone.code); }, true));
        body.appendChild(row);
      });
    });
    (data().info || []).forEach(function (field) {
      var row = el("div", "walk-finish__answer");
      row.appendChild(el("strong", null, field.q));
      row.appendChild(el("p", null, field.value || tx("not_answered")));
      body.appendChild(row);
    });
    body.appendChild(button(tx("details"), info, true));
    var zone = (data().zones || []).filter(function (z) { return !z.equipment; })[0];
    if (zone) body.appendChild(button(tx("advice"), function () { edit(null, zone.code); }, true));
    var languages = review.report_langs || [];
    var select = el("select", "walk-input");
    select.id = "finish-report-lang";
    var label = el("label", "walk-form__label", W.tx("walk.finish.report_lang")); label.htmlFor = select.id;
    if (languages.length !== 1) { var empty = el("option", null, tx("pick_language")); empty.value = ""; select.appendChild(empty); }
    languages.forEach(function (l) { var option = el("option", null, l.label); option.value = l.code; select.appendChild(option); });
    if (flow.language) select.value = flow.language;
    select.addEventListener("change", function () { flow.language = select.value; });
    body.appendChild(label); body.appendChild(select);
    var missing = (data().info || []).some(function (f) { return !f.value; });
    var skip = el("input"); skip.type = "checkbox"; skip.id = "finish-skip";
    if (missing) {
      var skipLabel = el("label", "walk-finish__consent");
      skipLabel.appendChild(skip); skipLabel.appendChild(el("span", null, tx("skip_confirm")));
      body.appendChild(skipLabel);
    }
    var confirm = el("input"); confirm.type = "checkbox"; confirm.id = "finish-consent";
    var consent = el("label", "walk-finish__consent");
    consent.appendChild(confirm); consent.appendChild(el("span", null, tx("confirm")));
    body.appendChild(consent);
    var yes = button(tx("submit"), function () {
      if (!confirm.checked || (missing && !skip.checked)) { error(new Error(tx("confirm_required"))); return; }
      if (!select.value) { error(new Error(W.tx("walk.finish.err.lang"))); return; }
      submit(yes, select.value, missing && skip.checked);
    });
    body.appendChild(yes);
    body.appendChild(button(tx("chat"), function () { close(); chatAsk(); }, true));
  }
  function submit(yes, language, skip) {
    if (flow.busy) return;
    flow.busy = true; yes.disabled = true;
    post({ op: "finish_submit", run_id: flow.run, revision: flow.review.revision,
      report_lang: language, skip_missing_info: skip, confirmed: true }).then(function (res) {
      flow.busy = false; status(res);
    }).catch(function (err) { flow.busy = false; yes.disabled = false; error(err); });
  }
  function status(res) {
    if (!view) return;
    var body = frame(tx("status"));
    if (res.status === "completed") {
      apply(res.data); W.local.drop(key());
      body.appendChild(el("p", null, tx("completed")));
      body.appendChild(button(W.tx("walk.sheet.close"), close));
      return;
    }
    if (res.status === "ready") {
      body.appendChild(el("p", null, tx("retry")));
      body.appendChild(button(tx("review"), function () { fetchReview().then(summary).catch(error); }));
      return;
    }
    body.appendChild(el("p", null, tx("building")));
    poll = window.setTimeout(checkStatus, 1500);
  }
  function checkStatus() {
    if (!view) return;
    var mine = flow;
    post({ op: "finish_status", run_id: flow.run }).then(function (res) { if (flow === mine) status(res); }).catch(function (err) {
      if (flow !== mine || !view) return;
      error(err);
      view.querySelector(".walk-finish__body").appendChild(button(tx("check_status"), checkStatus));
    });
  }
  function ask() {
    if (view || document.getElementById("walk-confirm")) return;
    var d = data();
    flow = { key: d.key, run: d.run_id, fields: {}, busy: false };
    var saved = W.local.get(key());
    if (saved && saved.run_id === flow.run && saved.fields && typeof saved.fields === "object") {
      Object.keys(saved.fields).forEach(function (code) { if (typeof saved.fields[code] === "string") flow.fields[code] = saved.fields[code]; });
    }
    loading();
    var mine = flow;
    post({ op: "finish_status", run_id: flow.run }).then(function (res) {
      if (flow !== mine || !view) return;
      if (res.status !== "ready") { status(res); return; }
      return fetchReview().then(info);
    }).catch(function (err) {
      if (flow !== mine || !view) return;
      info(); error(err);
    });
  }
  W.finish.ask = ask;
})();
