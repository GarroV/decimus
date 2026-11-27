/* Явные ответы технического контроля: одна проверка и одни находки с обходом. */
(function () {
  "use strict";
  var W = window.DecimusWalk, el = W.el, tx = W.tx;
  var T = W.technical = {zone: "", filter: "pending", busy: false, reasonKey: null, reason: ""};

  function data() { return (W.state.data || {}).technical || {}; }
  function enabled() { return !!data().enabled; }
  function writable() { return W.state.data && !W.state.data.sealed && !T.busy; }
  function key(c) { return c.id + ":" + c.zone; }
  function zone(code) { return (W.state.data.zones || []).filter(function (z) { return z.code === code; })[0]; }
  function zoneTitle(code) { var z = zone(code); return z ? (z.title || z.name || code) : code; }
  function terminal(c) { return c.terminal === true || ["ok", "issue", "recorded", "na"].indexOf(c.status) !== -1; }
  function btn(cls, text, action) { var b = W.button(cls, text, action); b.disabled = !writable(); return b; }

  function save(c, status, extra) {
    if (!writable()) return;
    var runId = W.state.data.run_id;
    var body = Object.assign({run_id: runId, check_id: c.id, zone: c.zone, status: status}, extra || {});
    var revision = W.state.data.revision || data().revision;
    if (revision) body.revision = revision;
    T.busy = true;
    W.render();
    W.post(W.urls.technical, body).then(function (res) {
      if (!res.ok) throw new Error((res.body || {}).message || tx("walk.error"));
      T.reasonKey = null;
      W.haptic("success");
      if (W.state.data.run_id === runId) W.apply(res.body);
      W.toast(tx("walk.technical.saved"));
    }).catch(function (err) {
      W.haptic("error");
      W.toast(err.message === "Failed to fetch" ? tx("walk.err.network") : err.message, "err");
    }).finally(function () { T.busy = false; W.render(); });
  }

  function finding(n) {
    var found = null;
    (W.state.data.zones || []).some(function (z) {
      return (z.recorded || []).some(function (r) { if (r.n === n) { found = {record: r, zone: z.code}; return true; } return false; });
    });
    return found;
  }

  function hasViolationLevel(code) {
    var item = (W.state.data.items || []).filter(function (i) { return i.code === code; })[0];
    return !!(item && (item.levels || []).some(function (level) { return /^D[1-3]$/.test(level); }));
  }

  function addRecord(c, mode) {
    mode = mode || (c.kind === "info" ? "measure" : "violation");
    function open(code) {
      W.toast(tx("walk.technical.after_record"));
      W.sheet.open({mode: mode, zone: c.zone, code: code});
    }
    var codes = c.item_codes || [];
    if (mode === "violation") codes = codes.filter(hasViolationLevel);
    if (codes.length === 1) { open(codes[0]); return; }
    W.menu.open({title: tx("walk.technical.choose_item"), options: codes.map(function (code) {
      var item = (W.state.data.items || []).filter(function (i) { return i.code === code; })[0];
      return {label: item ? (item.label ? item.label + " · " : "") + item.q : c.title, value: code};
    }), onPick: open});
  }

  function link(c) {
    var options = (c.candidate_finding_numbers || []).map(function (n) {
      var f = finding(n);
      return f ? {label: f.record.text, hint: f.record.level, value: n} : null;
    }).filter(Boolean);
    options.push({label: tx("walk.technical.new"), value: "new"});
    W.menu.open({title: tx("walk.technical.choose"), options: options, onPick: function (n) {
      if (n === "new") addRecord(c);
      else {
        var f = finding(n);
        save(c, f && f.record.level === "D0" ? "recorded" : "issue", {finding_numbers: [n]});
      }
    }});
  }

  function card(c) {
    var node = el("article", "walk-technical__check is-" + c.status);
    node.setAttribute("data-technical-check", key(c));
    var top = el("div", "walk-technical__meta");
    top.appendChild(el("span", "", tx("walk.technical.status." + c.status)));
    top.appendChild(el("span", "", tx(c.required ? "walk.technical.required" : "walk.technical.optional")));
    node.appendChild(top);
    node.appendChild(el("h3", "walk-technical__title", c.title));
    if (c.applicability) node.appendChild(el("p", "walk-technical__hint", c.applicability));
    if (c.guidance) {
      var d = el("details", "walk-technical__guidance");
      d.appendChild(el("summary", "", tx("walk.technical.guidance")));
      d.appendChild(el("p", "", c.guidance));
      node.appendChild(d);
    }
    if (c.reason) node.appendChild(el("p", "walk-technical__reason", c.reason));
    (c.finding_numbers || []).forEach(function (n) {
      var f = finding(n);
      if (f) node.appendChild(btn("walk-link", f.record.text, function () { W.sheet.open(f); }));
    });
    if (!W.state.data.sealed) {
      var actions = el("div", "walk-technical__actions");
      if (c.status !== "issue" && c.status !== "recorded" && c.status !== "ok" && !c.requires_photo) {
        actions.appendChild(btn("walk-btn", tx("walk.technical.ok"), function () { save(c, "ok"); }));
      }
      if (!terminal(c)) {
        if ((c.candidate_finding_numbers || []).length) {
          node.appendChild(el("p", "walk-technical__hint", tx("walk.technical.link_hint")));
          actions.appendChild(btn("walk-btn", tx("walk.technical.link"), function () { link(c); }));
        }
        if (c.kind === "info") actions.appendChild(btn("walk-link", tx("walk.technical.info"), function () { addRecord(c, "measure"); }));
        if ((c.item_codes || []).some(hasViolationLevel)) actions.appendChild(btn("walk-link", tx("walk.technical.issue"), function () { addRecord(c, "violation"); }));
      }
      if (c.status !== "issue" && c.status !== "recorded" && c.status !== "na") {
        actions.appendChild(btn("walk-link", tx("walk.technical.na"), function () { T.reasonKey = key(c); T.reason = ""; W.render(); }));
      }
      if (terminal(c)) actions.appendChild(btn("walk-link", tx("walk.technical.reset"), function () { save(c, "pending"); }));
      node.appendChild(actions);
      if (T.reasonKey === key(c)) {
        var label = el("label", "walk-technical__reason-label", tx("walk.technical.reason"));
        var input = el("textarea", "walk-technical__input");
        input.value = T.reason;
        input.maxLength = 1000;
        input.rows = 3;
        input.placeholder = tx("walk.technical.reason_hint");
        input.addEventListener("input", function () { T.reason = input.value; });
        label.appendChild(input);
        node.appendChild(label);
        node.appendChild(btn("walk-btn", tx("walk.technical.save"), function () { save(c, "na", {reason: T.reason}); }));
        node.appendChild(btn("walk-link", tx("walk.technical.cancel"), function () { T.reasonKey = null; W.render(); }));
      }
    }
    return node;
  }

  function progress() {
    var box = el("div", "walk-technical__progress");
    box.appendChild(el("strong", "", tx("walk.technical.progress", {done: data().checked || 0, total: data().total || 0})));
    box.appendChild(el("span", "", tx("walk.technical.remaining", {count: data().required_pending || 0})));
    var meter = el("progress");
    meter.max = data().total || 1;
    meter.value = data().checked || 0;
    meter.setAttribute("aria-label", tx("walk.technical.title"));
    box.appendChild(meter);
    return box;
  }

  T.entry = function (zoneCode) {
    if (!enabled()) return null;
    var box = el("section", "walk-technical");
    box.appendChild(el("h2", "walk-technical__heading", tx("walk.technical.title")));
    box.appendChild(progress());
    box.appendChild(W.button("walk-link", tx("walk.technical.open"), function () { T.zone = ""; W.app.go("technical"); }));
    (data().checks || []).filter(function (c) { return c.zone === zoneCode && !terminal(c) && c.required; }).slice(0, 2).forEach(function (c) { box.appendChild(card(c)); });
    return box;
  };

  function select(label, options, value, change) {
    var wrap = el("label", "walk-technical__select-label", label);
    var input = el("select", "walk-technical__select");
    options.forEach(function (o) { var opt = el("option", "", o.title); opt.value = o.value; input.appendChild(opt); });
    input.value = value;
    input.addEventListener("change", function () { change(input.value); W.render(); });
    wrap.appendChild(input);
    return wrap;
  }

  T.render = function (root) {
    root.appendChild(W.button("walk-link", "‹ " + tx("walk.sheet.back"), function () { W.app.go("walk"); }));
    root.appendChild(el("h1", "walk-app__title", tx("walk.technical.title")));
    root.appendChild(el("p", "walk-technical__hint", tx("walk.technical.subtitle")));
    if (!enabled()) { W.app.go("walk"); return; }
    root.appendChild(progress());
    var filters = el("div", "walk-technical__filters");
    var zones = [{value: "", title: tx("walk.technical.all_zones")}];
    (W.state.data.zones || []).forEach(function (z) { if ((data().checks || []).some(function (c) { return c.zone === z.code; })) zones.push({value: z.code, title: zoneTitle(z.code)}); });
    filters.appendChild(select(tx("walk.technical.zone"), zones, T.zone, function (v) { T.zone = v; }));
    filters.appendChild(select(tx("walk.technical.show"), ["pending", "all", "issue"].map(function (v) { return {value: v, title: tx("walk.technical.filter." + v)}; }), T.filter, function (v) { T.filter = v; }));
    root.appendChild(filters);
    var checks = (data().checks || []).filter(function (c) {
      return (!T.zone || c.zone === T.zone) && (T.filter === "all" || (T.filter === "pending" ? !terminal(c) : c.status === "issue"));
    });
    if (!checks.length) root.appendChild(el("p", "walk-technical__hint", tx("walk.technical.empty")));
    var order = (W.state.data.zones || []).map(function (z) { return z.code; });
    checks.sort(function (a, b) { return order.indexOf(a.zone) - order.indexOf(b.zone); });
    var lastZone = null;
    checks.forEach(function (c) {
      if (lastZone !== c.zone) { root.appendChild(el("h2", "walk-technical__zone", zoneTitle(c.zone))); lastZone = c.zone; }
      root.appendChild(card(c));
    });
  };

  // Вернуть к конкретным пропускам до финального просмотра. Сервер проверяет
  // полноту повторно при завершении, независимо от этой подсказки интерфейса.
  if (W.finish && W.finish.ask) {
    var finishAsk = W.finish.ask;
    W.finish.ask = function () {
      if (enabled() && data().required_pending > 0) {
        T.filter = "pending";
        T.zone = "";
        W.toast(tx("walk.technical.finish_blocked"), "err");
        W.app.go("technical");
        return;
      }
      return finishAsk.apply(W.finish, arguments);
    };
  }
})();
