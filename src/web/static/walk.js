/* Мини-апп обхода (#418, D312): главный экран — что осмотрено, что было, что записано.
 *
 * Экран отвечает на вопрос аудитора на ходу: «что мне ещё посмотреть и
 * записать на этой точке?». Сверху вниз: точка и прогресс по зонам → что
 * было в прошлый раз → зоны с записями и кнопками записи → сведения о визите.
 * Форма записи — `walk-sheet.js`, кадры — `walk-photo.js`, общее — `walk-core.js`.
 *
 * Личные пометки («зона осмотрена», «исправлено») лежат в CloudStorage
 * Telegram у самого аудитора, ключом проверки. Вне Telegram (просмотр на
 * стенде) — localStorage. На оценку они не влияют и в отчёт не идут.
 */
(function () {
  "use strict";

  var W = window.DecimusWalk;
  var tg = W.tg;
  var root = W.root;
  var S = W.state;
  var tx = W.tx;
  var el = W.el;

  /* ── личные пометки ────────────────────────────────────────────────── */

  function hasCloud() { return W.supports("6.9") && !!tg.CloudStorage; }

  function parseMarks(raw) {
    try {
      var v = JSON.parse(raw || "{}");
      return { z: Array.isArray(v.z) ? v.z : [], f: Array.isArray(v.f) ? v.f : [] };
    } catch (e) {
      return { z: [], f: [] };
    }
  }

  function loadMarks(key, done) {
    if (hasCloud()) {
      tg.CloudStorage.getItem(key, function (err, value) { done(parseMarks(err ? null : value)); });
      return;
    }
    var raw = null;
    try { raw = window.localStorage.getItem(key); } catch (e) { raw = null; }
    done(parseMarks(raw));
  }

  function saveMarks() {
    var raw = JSON.stringify(S.marks);
    if (hasCloud()) { tg.CloudStorage.setItem(S.data.key, raw); return; }
    try { window.localStorage.setItem(S.data.key, raw); } catch (e) { /* живёт до закрытия */ }
  }

  function toggle(list, value) {
    var next = list.filter(function (v) { return v !== value; });
    if (next.length === list.length) next.push(value);
    return next;
  }

  /* ── расчёт ────────────────────────────────────────────────────────── */

  function fixKey(item, zone) { return item.code + "|" + zone.code; }

  function zoneDone(zone) { return zone.recorded.length > 0 || S.marks.z.indexOf(zone.code) !== -1; }

  function rechecked(item, zone) { return item.again || S.marks.f.indexOf(fixKey(item, zone)) !== -1; }

  function openPrevious(zone) {
    return zone.previous.filter(function (p) { return !rechecked(p, zone); }).length;
  }

  function hasMeasures(zone) {
    return S.data.items.some(function (i) { return i.measure && (!i.zones.length || i.zones.indexOf(zone.code) !== -1); });
  }

  function writable() { return !S.data.sealed; }

  /* ── шапка и прошлое ───────────────────────────────────────────────── */

  function renderHead(zones) {
    var done = zones.filter(zoneDone);
    var head = el("header", "walk-head");
    var top = el("div", "walk-head__top");
    top.appendChild(el("h1", "walk-head__unit", S.data.unit));
    top.appendChild(el("span", "walk-head__date", W.day(S.data.date)));
    head.appendChild(top);
    if (S.data.sealed) head.appendChild(el("p", "walk-banner", tx("walk.sealed")));

    var all = done.length === zones.length;
    head.appendChild(el("p", "walk-head__progress",
      all ? tx("walk.all_done") : tx("walk.progress", { done: done.length, total: zones.length })));
    var bar = el("div", "walk-bar");
    bar.setAttribute("aria-hidden", "true");
    zones.forEach(function (z) { bar.appendChild(el("span", "walk-bar__seg" + (zoneDone(z) ? " is-done" : ""))); });
    head.appendChild(bar);

    var left = zones.filter(function (z) { return !zoneDone(z); });
    if (left.length) {
      head.appendChild(el("p", "walk-head__label", tx("walk.left")));
      var chips = el("div", "walk-chips");
      left.forEach(function (z) {
        chips.appendChild(W.button("walk-chip" + (openPrevious(z) ? " has-attention" : ""), z.title,
          function () { openZone(z.code, true); }));
      });
      head.appendChild(chips);
    }
    var recorded = zones.some(function (z) { return z.recorded.length; });
    if (!S.marks.z.length && !recorded && writable()) head.appendChild(el("p", "walk-head__how", tx("walk.how")));
    return head;
  }

  function renderPrevious(zones) {
    var box = el("section", "walk-prev");
    if (S.data.previous_unavailable) {
      box.appendChild(el("p", "walk-prev__text", tx("walk.prev.unavailable")));
      return box;
    }
    if (!S.data.previous) {
      box.classList.add("is-quiet");
      box.appendChild(el("p", "walk-prev__text", tx("walk.prev.none")));
      return box;
    }
    box.appendChild(el("h2", "walk-prev__title", tx("walk.prev.title", { date: W.day(S.data.previous.date) })));
    if (!S.data.previous.count) {
      box.appendChild(el("p", "walk-prev__text", tx("walk.prev.clean")));
      return box;
    }
    box.appendChild(el("p", "walk-prev__text", tx("walk.prev.summary", { count: S.data.previous.count })));
    var left = zones.reduce(function (sum, z) { return sum + openPrevious(z); }, 0);
    if (left) {
      box.classList.add("has-attention");
      box.appendChild(el("p", "walk-prev__left", tx("walk.prev.left", { count: left })));
    }
    return box;
  }

  /* ── зона ──────────────────────────────────────────────────────────── */

  function renderPreviousItem(item, zone) {
    var row = el("li", "walk-item walk-item--prev");
    var line = el("div", "walk-item__line");
    line.appendChild(W.level(item.level));
    line.appendChild(el("span", "walk-item__text", item.text));
    row.appendChild(line);
    if (item.again) {
      row.appendChild(el("span", "walk-tag walk-tag--again", tx("walk.item.again")));
      return row;
    }
    var fixed = S.marks.f.indexOf(fixKey(item, zone)) !== -1;
    var actions = el("div", "walk-row");
    var fix = W.button("walk-fix" + (fixed ? " is-on" : ""), tx("walk.item.fixed"), function () {
      S.marks.f = toggle(S.marks.f, fixKey(item, zone));
      W.haptic();
      saveMarks();
      render();
    });
    fix.setAttribute("aria-pressed", fixed ? "true" : "false");
    actions.appendChild(fix);
    if (!fixed && writable()) {
      actions.appendChild(W.button("walk-fix walk-fix--again", tx("walk.item.record_repeat"), function () {
        var known = S.data.items.filter(function (i) { return i.code === item.code; })[0];
        W.sheet.open({
          mode: "violation",
          zone: zone.code,
          code: known ? item.code : null,
          level: known && known.levels.indexOf(item.level) !== -1 ? item.level : null,
          repeat: item.level === "D1" || item.level === "D2",
        });
      }));
    }
    row.appendChild(actions);
    if (!fixed) row.appendChild(el("p", "walk-item__hint", tx("walk.item.hint")));
    return row;
  }

  function renderRecord(rec, zone) {
    var row = el("li", "walk-rec");
    var b = W.button("walk-rec__open", null, function () {
      if (writable()) W.sheet.open({ record: rec, zone: zone.code });
    });
    b.setAttribute("aria-label", tx("walk.rec.edit"));
    if (rec.photos.length) {
      var shot = el("span", "walk-rec__shot");
      shot.appendChild(W.photo.thumb(rec.photos[0]));
      if (rec.photos.length > 1) shot.appendChild(el("span", "walk-rec__more", "+" + (rec.photos.length - 1)));
      b.appendChild(shot);
    }
    var words = el("span", "walk-rec__words");
    var line = el("span", "walk-item__line");
    line.appendChild(W.level(rec.level));
    line.appendChild(el("span", "walk-item__text", rec.text));
    words.appendChild(line);
    if (rec.comment) words.appendChild(el("span", "walk-rec__comment", tx("walk.rec.comment", { text: rec.comment })));
    if (rec.repeat) words.appendChild(el("span", "walk-tag walk-tag--again", tx("walk.rec.repeat")));
    b.appendChild(words);
    if (writable()) b.appendChild(el("span", "walk-rec__chev", "›"));
    row.appendChild(b);
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
      var now = el("ul", "walk-list walk-list--records");
      zone.recorded.forEach(function (r) { now.appendChild(renderRecord(r, zone)); });
      body.appendChild(now);
    } else {
      body.appendChild(el("p", "walk-zone__note", tx("walk.zone.nothing")));
    }
    if (writable()) {
      var add = el("div", "walk-row walk-row--add");
      add.appendChild(W.button("walk-add", "+ " + tx("walk.add.short"), function () {
        W.sheet.open({ mode: "violation", zone: zone.code });
      }));
      if (hasMeasures(zone)) {
        add.appendChild(W.button("walk-add walk-add--quiet", "+ " + tx("walk.add.short_measure"), function () {
          W.sheet.open({ mode: "measure", zone: zone.code });
        }));
      }
      body.appendChild(add);
    }
    if (zone.recorded.length) {
      body.appendChild(el("p", "walk-zone__note", tx("walk.zone.auto")));
      return body;
    }
    var marked = S.marks.z.indexOf(zone.code) !== -1;
    body.appendChild(W.button("walk-mark walk-mark--zone" + (marked ? " is-on" : ""),
      marked ? tx("walk.zone.unmark") : tx("walk.zone.mark"), function () {
        S.marks.z = toggle(S.marks.z, zone.code);
        W.haptic();
        saveMarks();
        if (!marked) S.open = null;
        render();
      }));
    return body;
  }

  function renderZone(zone) {
    var done = zoneDone(zone);
    var isOpen = S.open === zone.code;
    var item = el("li", "walk-zone" + (done ? " is-done" : "") + (isOpen ? " is-open" : ""));
    item.id = "zone-" + zone.code;
    var head = W.button("walk-zone__head", null, function () { openZone(zone.code, false); });
    head.setAttribute("aria-expanded", isOpen ? "true" : "false");
    head.appendChild(el("span", "walk-zone__check", done ? "✓" : ""));
    head.appendChild(el("span", "walk-zone__title", zone.title));
    var meta = el("span", "walk-zone__meta");
    if (zone.recorded.length) meta.appendChild(el("span", "walk-count", tx("walk.count.now", { count: zone.recorded.length })));
    var attention = openPrevious(zone);
    if (attention) meta.appendChild(el("span", "walk-count walk-count--attention", tx("walk.count.before", { count: attention })));
    head.appendChild(meta);
    item.appendChild(head);
    if (isOpen) item.appendChild(renderZoneBody(zone));
    return item;
  }

  function openZone(code, scroll) {
    S.open = S.open === code && !scroll ? null : code;
    render();
    if (scroll) {
      var target = document.getElementById("zone-" + code);
      if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  /* ── сведения о визите ─────────────────────────────────────────────── */

  function infoInput(field) {
    if (field.kind === "yes_no") {
      var seg = el("div", "walk-seg");
      var yes = tx("walk.info.yes");
      var no = tx("walk.info.no");
      [["yes", yes], ["no", no]].forEach(function (pair) {
        var on = field.value === pair[1];
        var b = W.button("walk-seg__opt" + (on ? " is-on" : ""), pair[1], function () {
          if (writable()) saveInfo(field.code, pair[0]);
        });
        b.disabled = !writable();
        seg.appendChild(b);
      });
      return { node: seg };
    }
    var input;
    if (field.kind === "date") {
      input = el("input", "walk-input");
      input.type = field.code === "INF05" ? "datetime-local" : "date";
      input.value = isoOf(field.value, input.type);
    } else {
      input = el("textarea", "walk-area");
      input.rows = 2;
      input.maxLength = 1000;
      input.value = field.value;
    }
    input.disabled = !writable();
    return { node: input, input: input };
  }

  /** «07.10.2026 14:30» из отчёта → значение поля телефона. */
  function isoOf(value, type) {
    var m = /^(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{2}):(\d{2}))?/.exec(value || "");
    if (!m) return "";
    var day = m[3] + "-" + m[2] + "-" + m[1];
    return type === "datetime-local" ? day + "T" + (m[4] || "12") + ":" + (m[5] || "00") : day;
  }

  function renderInfo() {
    if (!S.data.info.length) return null;
    var box = el("section", "walk-info");
    box.appendChild(el("h2", "walk-info__title", tx("walk.info.title")));
    box.appendChild(el("p", "walk-info__hint", tx("walk.info.hint")));
    S.data.info.forEach(function (field) {
      var row = el("div", "walk-info__field");
      row.appendChild(el("label", "walk-form__label", field.q));
      var made = infoInput(field);
      row.appendChild(made.node);
      if (made.input && writable()) {
        var save = W.button("walk-btn walk-btn--small", tx("walk.info.save"), function () {
          saveInfo(field.code, made.input.value);
        });
        save.hidden = true;
        made.input.addEventListener("input", function () { save.hidden = made.input.value === field.value; });
        made.input.addEventListener("change", function () { save.hidden = false; });
        row.appendChild(save);
      }
      if (!field.value && !writable()) row.appendChild(el("p", "walk-form__hint", tx("walk.info.empty")));
      box.appendChild(row);
    });
    return box;
  }

  function saveInfo(code, value) {
    W.post(W.urls.info, { code: code, value: value }).then(function (res) {
      if (!res.ok) throw new Error((res.body && res.body.message) || tx("walk.error"));
      W.haptic("success");
      W.toast(tx("walk.info.saved"), "ok");
      W.apply(res.body);
    }).catch(function (err) {
      W.haptic("error");
      W.toast(err && err.message && err.message !== "Failed to fetch" ? err.message : tx("walk.err.network"), "err");
    });
  }

  /* ── экран целиком ─────────────────────────────────────────────────── */

  function render() {
    var y = window.scrollY;
    root.textContent = "";
    if (S.data.state === "none") {
      renderEmpty(tx("walk.none.title"), tx("walk.none.text"));
      return;
    }
    root.appendChild(renderHead(S.data.zones));
    root.appendChild(renderPrevious(S.data.zones));
    var list = el("ul", "walk-zones");
    S.data.zones.forEach(function (z) { list.appendChild(renderZone(z)); });
    root.appendChild(list);
    var info = renderInfo();
    if (info) root.appendChild(info);
    if (writable()) {
      var dock = el("div", "walk-dock");
      dock.appendChild(W.button("walk-mark", tx("walk.add.violation"), function () {
        W.sheet.open({ mode: "violation", zone: S.open });
      }));
      root.appendChild(dock);
    }
    window.scrollTo(0, y);
  }

  function renderEmpty(title, text) {
    root.textContent = "";
    var box = el("section", "walk-empty");
    box.appendChild(el("h1", "walk-empty__title", title));
    if (text) box.appendChild(el("p", "walk-empty__text", text));
    if (W.inTelegram()) box.appendChild(W.button("walk-mark", tx("walk.back"), function () { tg.close(); }));
    root.appendChild(box);
  }

  /** Принять свежие данные с сервера (ответ на чтение или запись). */
  W.apply = function (body, keepSheet) {
    var first = !S.data || S.data.key !== body.key;
    S.data = body;
    document.documentElement.lang = body.lang;
    if (body.state !== "active") { if (!keepSheet) W.sheet.close(true); render(); return; }
    if (first) loadMarks(body.key, function (m) { S.marks = m; render(); });
    else render();
  };

  /* ── загрузка ──────────────────────────────────────────────────────── */

  function load() {
    // Пока открыта форма, данные под ней не меняются: перерисовка унесла бы
    // выбранный пункт из-под пальца. Свежие придут ответом на сохранение.
    if (W.sheet.isOpen()) return;
    W.post(W.urls.data, (tg && tg.initData) || "", "text/plain")
      .then(function (res) {
        if (!res.ok) {
          S.data = { texts: (res.body && res.body.texts) || {} };
          renderEmpty(tx(res.body && res.body.error === "closed" ? "walk.closed" : "walk.error"));
          return;
        }
        W.apply(res.body);
      })
      .catch(function () {
        S.data = S.data || { texts: {} };
        renderEmpty(tx("walk.error") === "walk.error" ? "⚠︎" : tx("walk.error"));
      });
  }

  function theme() {
    var dark = tg && tg.colorScheme === "dark";
    if (!W.inTelegram()) dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  }

  if (tg) {
    tg.ready();
    tg.expand();
    // Прокрутка длинной формы вниз не должна сворачивать окно (Bot API 7.7).
    if (W.supports("7.7") && tg.disableVerticalSwipes) tg.disableVerticalSwipes();
    tg.onEvent("themeChanged", theme);
    // Аудитор вернулся из чата, где мог записать нарушение, — данные свежие.
    tg.onEvent("activated", load);
  }
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible" && S.data) load();
  });
  theme();
  load();
})();
