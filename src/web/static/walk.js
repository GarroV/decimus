/* Мини-апп обхода (#418): рисует экран из `/tg/walk/data`.
 *
 * Что здесь решено:
 * - строки — только из ответа сервера (`texts`), своих в скрипте нет;
 * - разметка — через textContent, без innerHTML: формулировки приходят из
 *   слов аудитора и методики, а не из нашего кода;
 * - личные пометки («зона осмотрена», «исправлено») лежат в CloudStorage
 *   Telegram у самого аудитора, ключом проверки. Вне Telegram (просмотр на
 *   стенде) — localStorage. На оценку они не влияют и в отчёт не идут.
 */
(function () {
  "use strict";

  var tg = window.Telegram && window.Telegram.WebApp;
  var root = document.getElementById("walk");
  var data = null;
  var marks = { z: [], f: [] };
  var open = null;

  /* ── хранилище пометок ─────────────────────────────────────────────── */

  function hasCloud() {
    return !!(tg && tg.initData && tg.CloudStorage && tg.isVersionAtLeast && tg.isVersionAtLeast("6.9"));
  }

  function loadMarks(key, done) {
    function parse(raw) {
      try {
        var v = JSON.parse(raw || "{}");
        return { z: Array.isArray(v.z) ? v.z : [], f: Array.isArray(v.f) ? v.f : [] };
      } catch (e) {
        return { z: [], f: [] };
      }
    }
    if (hasCloud()) {
      tg.CloudStorage.getItem(key, function (err, value) { done(parse(err ? null : value)); });
      return;
    }
    var raw = null;
    try { raw = window.localStorage.getItem(key); } catch (e) { raw = null; }
    done(parse(raw));
  }

  function saveMarks() {
    var raw = JSON.stringify(marks);
    if (hasCloud()) {
      tg.CloudStorage.setItem(data.key, raw);
      return;
    }
    try { window.localStorage.setItem(data.key, raw); } catch (e) { /* пометка живёт до закрытия */ }
  }

  function toggle(list, value) {
    var next = list.filter(function (v) { return v !== value; });
    if (next.length === list.length) next.push(value);
    return next;
  }

  function haptic() {
    if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred("light");
  }

  /* ── текст ─────────────────────────────────────────────────────────── */

  function tx(key, params) {
    var s = (data && data.texts && data.texts[key]) || key;
    Object.keys(params || {}).forEach(function (p) { s = s.split("{" + p + "}").join(String(params[p])); });
    return s;
  }

  function day(iso) {
    var d = new Date(iso + "T12:00:00");
    try {
      return d.toLocaleDateString(data.lang, { day: "numeric", month: "long" });
    } catch (e) {
      return iso;
    }
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  /* ── расчёт ────────────────────────────────────────────────────────── */

  function fixKey(item, zone) { return item.code + "|" + zone.code; }

  function zoneDone(zone) {
    return zone.recorded.length > 0 || marks.z.indexOf(zone.code) !== -1;
  }

  function rechecked(item, zone) {
    return item.again || marks.f.indexOf(fixKey(item, zone)) !== -1;
  }

  function openPrevious(zone) {
    return zone.previous.filter(function (p) { return !rechecked(p, zone); }).length;
  }

  /* ── экран ─────────────────────────────────────────────────────────── */

  function level(code) {
    return el("span", "walk-level walk-level--" + String(code).toLowerCase(), code);
  }

  function renderHead(zones) {
    var done = zones.filter(zoneDone);
    var head = el("header", "walk-head");
    var top = el("div", "walk-head__top");
    top.appendChild(el("h1", "walk-head__unit", data.unit));
    top.appendChild(el("span", "walk-head__date", day(data.date)));
    head.appendChild(top);

    var all = done.length === zones.length;
    head.appendChild(el("p", "walk-head__progress",
      all ? tx("walk.all_done") : tx("walk.progress", { done: done.length, total: zones.length })));

    var bar = el("div", "walk-bar");
    bar.setAttribute("aria-hidden", "true");
    zones.forEach(function (z) {
      bar.appendChild(el("span", "walk-bar__seg" + (zoneDone(z) ? " is-done" : "")));
    });
    head.appendChild(bar);

    var left = zones.filter(function (z) { return !zoneDone(z); });
    if (left.length) {
      head.appendChild(el("p", "walk-head__label", tx("walk.left")));
      var chips = el("div", "walk-chips");
      left.forEach(function (z) {
        var chip = el("button", "walk-chip" + (openPrevious(z) ? " has-attention" : ""), z.title);
        chip.type = "button";
        chip.addEventListener("click", function () { openZone(z.code, true); });
        chips.appendChild(chip);
      });
      head.appendChild(chips);
    }
    if (!marks.z.length) head.appendChild(el("p", "walk-head__how", tx("walk.how")));
    return head;
  }

  function renderPrevious(zones) {
    var box = el("section", "walk-prev");
    if (data.previous_unavailable) {
      box.appendChild(el("p", "walk-prev__text", tx("walk.prev.unavailable")));
      return box;
    }
    if (!data.previous) {
      box.classList.add("is-quiet");
      box.appendChild(el("p", "walk-prev__text", tx("walk.prev.none")));
      return box;
    }
    box.appendChild(el("h2", "walk-prev__title", tx("walk.prev.title", { date: day(data.previous.date) })));
    if (!data.previous.count) {
      box.appendChild(el("p", "walk-prev__text", tx("walk.prev.clean")));
      return box;
    }
    box.appendChild(el("p", "walk-prev__text", tx("walk.prev.summary", { count: data.previous.count })));
    var left = zones.reduce(function (sum, z) { return sum + openPrevious(z); }, 0);
    if (left) {
      box.classList.add("has-attention");
      box.appendChild(el("p", "walk-prev__left", tx("walk.prev.left", { count: left })));
    }
    return box;
  }

  function renderPreviousItem(item, zone) {
    var row = el("li", "walk-item walk-item--prev");
    var line = el("div", "walk-item__line");
    line.appendChild(level(item.level));
    line.appendChild(el("span", "walk-item__text", item.text));
    row.appendChild(line);
    if (item.again) {
      row.appendChild(el("span", "walk-tag walk-tag--again", tx("walk.item.again")));
      return row;
    }
    var fixed = marks.f.indexOf(fixKey(item, zone)) !== -1;
    var btn = el("button", "walk-fix" + (fixed ? " is-on" : ""), tx("walk.item.fixed"));
    btn.type = "button";
    btn.setAttribute("aria-pressed", fixed ? "true" : "false");
    btn.addEventListener("click", function () {
      marks.f = toggle(marks.f, fixKey(item, zone));
      haptic();
      saveMarks();
      render();
    });
    row.appendChild(btn);
    if (!fixed) row.appendChild(el("p", "walk-item__hint", tx("walk.item.hint")));
    return row;
  }

  function renderZoneBody(zone) {
    var body = el("div", "walk-zone__body");
    if (zone.previous.length) {
      body.appendChild(el("h3", "walk-zone__sub", tx("walk.zone.before")));
      var prev = el("ul", "walk-list");
      zone.previous.forEach(function (p) { prev.appendChild(renderPreviousItem(p, zone)); });
      body.appendChild(prev);
    }
    body.appendChild(el("h3", "walk-zone__sub", tx("walk.zone.now")));
    if (zone.recorded.length) {
      var now = el("ul", "walk-list");
      zone.recorded.forEach(function (r) {
        var row = el("li", "walk-item");
        var line = el("div", "walk-item__line");
        line.appendChild(level(r.level));
        line.appendChild(el("span", "walk-item__text", r.text));
        row.appendChild(line);
        now.appendChild(row);
      });
      body.appendChild(now);
      body.appendChild(el("p", "walk-zone__note", tx("walk.zone.auto")));
      return body;
    }
    body.appendChild(el("p", "walk-zone__note", tx("walk.zone.nothing")));
    var marked = marks.z.indexOf(zone.code) !== -1;
    var btn = el("button", "walk-mark" + (marked ? " is-on" : ""),
      marked ? tx("walk.zone.unmark") : tx("walk.zone.mark"));
    btn.type = "button";
    btn.addEventListener("click", function () {
      marks.z = toggle(marks.z, zone.code);
      haptic();
      saveMarks();
      if (!marked) open = null;
      render();
    });
    body.appendChild(btn);
    return body;
  }

  function renderZone(zone) {
    var done = zoneDone(zone);
    var item = el("li", "walk-zone" + (done ? " is-done" : "") + (open === zone.code ? " is-open" : ""));
    item.id = "zone-" + zone.code;
    var head = el("button", "walk-zone__head");
    head.type = "button";
    head.setAttribute("aria-expanded", open === zone.code ? "true" : "false");
    head.appendChild(el("span", "walk-zone__check", done ? "✓" : ""));
    head.appendChild(el("span", "walk-zone__title", zone.title));
    var meta = el("span", "walk-zone__meta");
    if (zone.recorded.length) meta.appendChild(el("span", "walk-count", tx("walk.count.now", { count: zone.recorded.length })));
    var attention = openPrevious(zone);
    if (attention) meta.appendChild(el("span", "walk-count walk-count--attention", tx("walk.count.before", { count: attention })));
    head.appendChild(meta);
    head.addEventListener("click", function () { openZone(zone.code, false); });
    item.appendChild(head);
    if (open === zone.code) item.appendChild(renderZoneBody(zone));
    return item;
  }

  function openZone(code, scroll) {
    open = open === code && !scroll ? null : code;
    render();
    if (scroll) {
      var node = document.getElementById("zone-" + code);
      if (node) node.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  function render() {
    root.textContent = "";
    if (data.state === "none") {
      renderEmpty(tx("walk.none.title"), tx("walk.none.text"));
      return;
    }
    root.appendChild(renderHead(data.zones));
    root.appendChild(renderPrevious(data.zones));
    var list = el("ul", "walk-zones");
    data.zones.forEach(function (z) { list.appendChild(renderZone(z)); });
    root.appendChild(list);
  }

  function renderEmpty(title, text) {
    root.textContent = "";
    var box = el("section", "walk-empty");
    box.appendChild(el("h1", "walk-empty__title", title));
    if (text) box.appendChild(el("p", "walk-empty__text", text));
    if (tg && tg.initData) {
      var back = el("button", "walk-mark", tx("walk.back"));
      back.type = "button";
      back.addEventListener("click", function () { tg.close(); });
      box.appendChild(back);
    }
    root.appendChild(box);
  }

  /* ── загрузка ──────────────────────────────────────────────────────── */

  function load() {
    fetch(root.getAttribute("data-endpoint"), {
      method: "POST",
      headers: { "Content-Type": "text/plain" },
      body: (tg && tg.initData) || "",
      credentials: "omit",
    })
      .then(function (r) { return r.json().then(function (body) { return { ok: r.ok, body: body }; }); })
      .then(function (res) {
        if (!res.ok) {
          data = { texts: res.body.texts || {} };
          renderEmpty(tx("walk.error"));
          return;
        }
        data = res.body;
        document.documentElement.lang = data.lang;
        if (data.state !== "active") { render(); return; }
        loadMarks(data.key, function (m) { marks = m; render(); });
      })
      .catch(function () {
        data = data || { texts: {} };
        renderEmpty(tx("walk.error") === "walk.error" ? "⚠︎" : tx("walk.error"));
      });
  }

  function theme() {
    var dark = tg && tg.colorScheme === "dark";
    if (!tg || !tg.initData) dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  }

  if (tg) {
    tg.ready();
    tg.expand();
    tg.onEvent("themeChanged", theme);
    // Аудитор вернулся из чата, где только что записал нарушение, — данные свежие.
    tg.onEvent("activated", load);
  }
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible" && data) load();
  });
  theme();
  load();
})();
