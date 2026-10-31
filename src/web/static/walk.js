/* Мини-апп обхода (#418, D312): главный экран — что осмотрено, что было, что записано.
 *
 * Экран отвечает на вопрос аудитора на ходу: «что мне ещё посмотреть и
 * записать на этой точке?». Он целиком про ОДНУ зону — ту, где аудитор
 * стоит: сверху точка, прогресс и прошлый раз одной строкой; под ними
 * переключатель зон (текущая, три подсказки «осталось», лист «Все зоны»
 * снизу по нажатию, свайп — соседняя зона); дальше прошлое, записанное,
 * чек-лист этой зоны; внизу — «+ Нарушение» и «Осмотрено →». Замеры —
 * последней остановкой «Печь и холодильники» (D315).
 * Зону засчитывает только явное «Осмотрено»: запись делает её «в работе».
 * Сведения о визите — отдельный лист из шапки.
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

  function loadMarks(data, done) {
    function owned(raw) {
      try { var v = JSON.parse(raw || "null"); return v && data.run_id && v.run_id === data.run_id; }
      catch (e) { return false; }
    }
    W.storedGet(data.key, function (raw) {
      if (owned(raw)) { done(parseMarks(raw)); return; }
      // Unknown legacy data stays at its original key for recovery.
      W.storedGet(data.legacy_key, function (legacy) {
        var recovered = parseMarks(legacy);
        done(owned(legacy) ? recovered : { z: [], f: [] },
          !owned(legacy) && (recovered.z.length || recovered.f.length) ? recovered : null);
      });
    });
  }

  function renderMarksRecovery() {
    var marks = S.recoveryMarks;
    if (!marks) return null;
    var panel = el("details", "walk-form__note walk-form__note--info");
    panel.appendChild(el("summary", "", tx("walk.draft.marks")));
    panel.appendChild(el("p", "", tx("walk.draft.unknown")));
    panel.appendChild(el("pre", "", tx("walk.draft.marks_preview", {
      zones: marks.z.join(", "), findings: marks.f.join(", ")
    })));
    panel.appendChild(W.button("walk-btn", tx("walk.draft.copy"), function () {
      if (!window.confirm(tx("walk.draft.marks_confirm"))) return;
      S.marks = {z: marks.z.slice(), f: marks.f.slice()};
      saveMarks();
      S.recoveryMarks = null;
      render();
    }));
    return panel;
  }

  function saveMarks() {
    var raw = JSON.stringify({ z: S.marks.z, f: S.marks.f, run_id: S.data.run_id });
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

  /** Осмотрена — только когда аудитор сам сказал «Осмотрено». Запись в зоне
   *  ещё не значит, что зону прошли целиком: она «в работе». */
  function zoneDone(zone) { return S.marks.z.indexOf(zone.code) !== -1; }

  function zoneStarted(zone) { return !zoneDone(zone) && zone.recorded.length > 0; }

  /** Сколько нарушений записано в зоне: замеры (D0), рекомендации и заметки — не нарушения. */
  function violationCount(zone) {
    return zone.recorded.filter(function (r) { return /^D[1-9]/.test(r.level); }).length;
  }

  /** Значок состояния зоны (D422): пунктир — не осмотрена; полкруга — в работе;
   *  галка — осмотрена, чисто; число — записано нарушений. Название — в aria-label и title. */
  function zoneIcon(zone) {
    var done = zoneDone(zone);
    var n = violationCount(zone);
    var node;
    var key;
    if (n) {
      node = el("span", "walk-zic is-found" + (done ? " is-done" : ""), String(n));
      key = done ? "found_done" : "found_open";
    } else if (done) {
      node = el("span", "walk-zic is-clean");
      node.appendChild(W.icon("check"));
      key = "clean";
    } else if (zone.recorded.length) {
      node = el("span", "walk-zic is-started");
      key = "started";
    } else {
      node = el("span", "walk-zic");
      key = "todo";
    }
    var label = tx("walk.zone.ic." + key, { count: n });
    node.setAttribute("role", "img");
    node.setAttribute("aria-label", label);
    node.title = label;
    return node;
  }

  function stateClass(zone) { return zoneDone(zone) ? " is-done" : zoneStarted(zone) ? " is-started" : ""; }

  var ADVICE_LEVEL = "R";

  function rechecked(item, zone) { return item.again || S.marks.f.indexOf(fixKey(item, zone)) !== -1; }

  function openPrevious(zone) {
    return zone.previous.filter(function (p) { return !rechecked(p, zone); }).length;
  }

  /* Замеры (D0: печь, холодильники, снимок изделия) собраны в одну остановку
   * обхода в конце списка — «Оборудование». В зонах их нет: так показания
   * снимаются одним заходом и не теряются среди нарушений. Запись замера
   * по-прежнему пишется в свою зону — остановка только собирает их. */
  var EQ_CODE = "__equipment";

  function withEquipment(body) {
    if (!body.zones || !body.items.some(function (i) { return i.measure; })) return body;
    var readings = [];
    var zones = body.zones.map(function (z) {
      z.recorded.forEach(function (r) {
        if (r.level === "D0") readings.push(Object.assign({}, r, { zone: z.code }));
      });
      return Object.assign({}, z, { recorded: z.recorded.filter(function (r) { return r.level !== "D0"; }) });
    });
    var eq = { code: EQ_CODE, title: tx("walk.eq.title"), equipment: true, previous: [], recorded: readings };
    return Object.assign({}, body, { zones: zones.concat([eq]) });
  }

  function zoneTitle(code) {
    var z = S.data.zones.filter(function (x) { return x.code === code; })[0];
    return z ? z.title : "";
  }

  function writable() { return !S.data.sealed; }

  function zoneIndex(code) {
    var zones = S.data.zones;
    for (var i = 0; i < zones.length; i++) if (zones[i].code === code) return i;
    return -1;
  }

  function zoneKey() { return "walk-zone:" + S.data.key; }

  /** Первая зона: где прошлое не перепроверено, затем любая неосмотренная. */
  function startZone() {
    var saved = W.local.get(zoneKey());
    if (saved && zoneIndex(saved) !== -1) return saved;
    var zones = S.data.zones;
    var pick = zones.filter(function (z) { return !zoneDone(z) && openPrevious(z); })[0] ||
      zones.filter(function (z) { return !zoneDone(z); })[0] || zones[0];
    return pick ? pick.code : null;
  }

  function current() {
    if (zoneIndex(S.open) === -1) S.open = startZone();
    return S.data.zones[zoneIndex(S.open)];
  }

  /** Следующая зона по кругу после этой: неосмотренная или по условию. */
  function nextOpen(code, predicate) {
    var zones = S.data.zones;
    var at = zoneIndex(code);
    for (var k = 1; k <= zones.length; k++) {
      var z = zones[(at + k) % zones.length];
      if (z.code !== code && (predicate ? predicate(z) : !zoneDone(z))) return z;
    }
    return null;
  }

  /** Перейти в зону. Направление — для сдвига содержимого. */
  function go(code, dir) {
    S.panel = false;
    S.list = false;
    if (code !== S.open) {
      S.dir = dir || (zoneIndex(code) > zoneIndex(S.open) ? 1 : -1);
      S.open = code;
      W.local.set(zoneKey(), code);
    }
    W.haptic();
    render();
    window.scrollTo(0, 0);
  }

  /** Перейти к зоне из чужого модуля — ссылка «Перейти» в уведомлении о записи (D445). */
  W.goZone = function (code) { if (zoneIndex(code) !== -1) go(code); };

  function infoCount() {
    var all = S.data.info || [];
    return { done: all.filter(function (f) { return !!f.value; }).length, total: all.length };
  }

  /* ── шапка: точка, прогресс, прошлый раз ───────────────────────────── */

  function renderTop(zones) {
    var top = el("header", "walk-top");
    var row = el("div", "walk-top__row");
    var home = W.button("walk-top__home", "‹", function () { W.app.go("home"); });
    home.setAttribute("aria-label", tx("walk.app.home"));
    row.appendChild(home);
    var title = el("div", "walk-top__title");
    title.appendChild(el("h1", "walk-top__unit", S.data.unit));
    title.appendChild(el("span", "walk-top__date", W.day(S.data.date)));
    row.appendChild(title);
    var info = infoCount();
    if (info.total) {
      var pill = W.hinted(W.button("walk-pill" + (info.done === info.total ? " is-done" : ""), null, openInfo), "info");
      pill.appendChild(el("span", null, tx("walk.info.open")));
      pill.appendChild(el("span", "walk-pill__count", info.done + "/" + info.total));
      row.appendChild(pill);
    }
    top.appendChild(row);

    var done = zones.filter(zoneDone).length;
    // Полоса — те же зоны, что в списке: нажатие открывает список (#1106). Её
    // нажимают первой, приняв за переключатель зон, — и не должна молчать.
    var progress = W.button("walk-progress", null, function () { setPanel(true); });
    progress.setAttribute("aria-label", tx("walk.switch.all") + ". " + tx("walk.progress", { done: done, total: zones.length }));
    var bar = el("div", "walk-progress__bar");
    bar.setAttribute("aria-hidden", "true");
    zones.forEach(function (z) {
      bar.appendChild(el("span", "walk-progress__seg" + stateClass(z) + (z.code === S.open ? " is-here" : "")));
    });
    progress.appendChild(bar);
    var count = el("span", "walk-progress__count", done + "/" + zones.length);
    count.setAttribute("aria-label", tx("walk.progress", { done: done, total: zones.length }));
    progress.appendChild(count);
    // Стрелки соседних зон — по бокам полосы (владелец, 21.10.2026): туда
    // смотрят первым делом, а у названия зоны их не замечали.
    var at = zoneIndex(S.open);
    var n = zones.length;
    var nav = el("div", "walk-progress-row");
    var back = W.button("walk-switch__arrow walk-switch__arrow--top", "‹", function () { go(zones[(at - 1 + n) % n].code, -1); });
    back.setAttribute("aria-label", tx("walk.switch.prev"));
    var fwd = W.button("walk-switch__arrow walk-switch__arrow--top", "›", function () { go(zones[(at + 1) % n].code, 1); });
    fwd.setAttribute("aria-label", tx("walk.switch.next"));
    if (n > 1) nav.appendChild(back);
    nav.appendChild(progress);
    if (n > 1) nav.appendChild(fwd);
    top.appendChild(nav);

    top.appendChild(renderPrevLine(zones));
    if (S.data.sealed) top.appendChild(el("p", "walk-banner", tx("walk.sealed")));
    return top;
  }

  function renderPrevLine(zones) {
    if (S.data.previous_unavailable) return el("p", "walk-prevline", tx("walk.prev.unavailable"));
    if (!S.data.previous) return el("p", "walk-prevline", tx("walk.prev.none"));
    var date = W.day(S.data.previous.date);
    if (!S.data.previous.count) return el("p", "walk-prevline", tx("walk.prev.line_clean", { date: date }));
    var left = zones.reduce(function (sum, z) { return sum + openPrevious(z); }, 0);
    if (!left) return el("p", "walk-prevline is-ok", tx("walk.prev.line_done", { date: date }));
    // Нажатие ведёт в ближайшую зону, где прошлое ещё не перепроверено.
    return W.button("walk-prevline is-attention", tx("walk.prev.line", { date: date, count: left }) + "  ›", function () {
      var here = current();
      var z = openPrevious(here) ? here : nextOpen(here.code, function (x) { return openPrevious(x) > 0; });
      if (z) go(z.code);
    });
  }

  /* ── переключатель зон: текущая, подсказки, весь список ────────────── */

  function tileMeta(z) {
    var parts = [];
    parts.push(zoneDone(z) ? tx("walk.tile.done") : zoneStarted(z) ? tx("walk.tile.started") : tx("walk.tile.todo"));
    if (z.recorded.length) parts.push(tx("walk.count.now", { count: z.recorded.length }));
    var attention = openPrevious(z);
    if (attention) parts.push(tx("walk.count.before", { count: attention }));
    return parts.join(" · ");
  }

  /** Весь список зон — лист снизу, под большим пальцем; выбор его закрывает. */
  function setPanel(open) {
    S.panel = open;
    var sheet = document.getElementById("walk-zones-sheet");
    if (sheet) {
      sheet.classList.toggle("is-open", open);
      sheet.inert = !open;
    }
    var main = root.querySelector(".walk-switch__main");
    if (main) main.setAttribute("aria-expanded", open ? "true" : "false");
    W.haptic();
  }

  function renderZonesSheet(zones, zone) {
    var old = document.getElementById("walk-zones-sheet");
    if (old) old.parentNode.removeChild(old);
    var sheet = el("div", "walk-zsheet" + (S.panel ? " is-open" : ""));
    sheet.id = "walk-zones-sheet";
    sheet.inert = !S.panel;
    var scrim = W.button("walk-zsheet__scrim", null, function () { setPanel(false); });
    scrim.setAttribute("aria-label", tx("walk.sheet.close"));
    sheet.appendChild(scrim);
    var card = el("div", "walk-zsheet__card");
    card.setAttribute("role", "dialog");
    var head = el("div", "walk-zsheet__head");
    head.appendChild(el("h2", "walk-zsheet__title", tx("walk.switch.all")));
    var done = zones.filter(zoneDone).length;
    head.appendChild(el("span", "walk-zsheet__count", done + "/" + zones.length));
    card.appendChild(head);
    var grid = el("div", "walk-panel__grid");
    zones.forEach(function (z) {
      var tile = W.button("walk-tile" + stateClass(z) + (openPrevious(z) ? " has-attention" : "") +
        (z.code === zone.code ? " is-here" : ""), null, function () { go(z.code); });
      var name = el("span", "walk-tile__name");
      name.appendChild(zoneIcon(z));
      name.appendChild(el("span", null, z.title));
      tile.appendChild(name);
      tile.appendChild(el("span", "walk-tile__meta", tileMeta(z)));
      grid.appendChild(tile);
    });
    card.appendChild(grid);
    sheet.appendChild(card);
    document.body.appendChild(sheet);
  }

  function renderSwitch(zones, zone) {
    var box = W.hinted(el("section", "walk-switch"), "zones");
    var bar = el("div", "walk-switch__bar");
    var main = W.button("walk-switch__main", null, function () { setPanel(!S.panel); });
    main.setAttribute("aria-expanded", S.panel ? "true" : "false");
    main.setAttribute("aria-label", zone.title + ". " + tx("walk.switch.all"));
    main.appendChild(zoneIcon(zone));
    var label = el("span", "walk-switch__label");
    label.appendChild(el("span", "walk-switch__name", zone.title));
    label.appendChild(el("span", "walk-switch__state",
      zoneDone(zone) ? tx("walk.tile.done") : zoneStarted(zone) ? tx("walk.tile.started") : tx("walk.tile.todo")));
    main.appendChild(label);
    // Без стрелки «▾»: список зон выезжает снизу, а стрелка вниз обещает
    // список, раскрывающийся под кнопкой (владелец, 08.10.2026). Стрелки
    // соседних зон — наверху, у полосы прогресса (21.10.2026).
    bar.appendChild(main);
    box.appendChild(bar);

    var left = zones.filter(function (z) { return !zoneDone(z) && z.code !== zone.code; });
    // Сначала те, где прошлое не перепроверено, дальше — порядок методики.
    left = left.filter(openPrevious).concat(left.filter(function (z) { return !openPrevious(z); }));
    var hints = el("div", "walk-hints");
    if (left.length) {
      hints.appendChild(el("span", "walk-hints__label", tx("walk.hint.left")));
      left.slice(0, 3).forEach(function (z) {
        hints.appendChild(W.button("walk-hint" + stateClass(z) + (openPrevious(z) ? " has-attention" : ""), z.title, function () { go(z.code); }));
      });
      if (left.length > 3) {
        hints.appendChild(W.button("walk-hint walk-hint--more", tx("walk.hint.more", { count: left.length - 3 }),
          function () { setPanel(true); }));
      }
    } else if (zoneDone(zone)) {
      hints.appendChild(el("span", "walk-hints__label is-ok", "✓ " + tx("walk.all_done")));
    }
    if (hints.childNodes.length) {
      box.appendChild(hints);
      // Лента листается вбок, а по виду этого не скажешь (#1106): пока справа
      // есть ещё, край затухает.
      var edge = function () { hints.classList.toggle("has-more", hints.scrollLeft + hints.clientWidth < hints.scrollWidth - 2); };
      hints.addEventListener("scroll", edge, { passive: true });
      window.requestAnimationFrame(edge);
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
    var advice = rec.level === ADVICE_LEVEL;
    // У рекомендации нет класса: вместо метки D-уровня — слово.
    var mark = rec.code === "NOTE" ? tx("walk.rec.note") : tx("walk.rec.advice");
    line.appendChild(advice ? el("span", "walk-level walk-level--advice", mark) : W.level(rec.level));
    line.appendChild(el("span", "walk-item__text", rec.text));
    words.appendChild(line);
    if (rec.comment) words.appendChild(el("span", "walk-rec__comment", tx("walk.rec.comment", { text: rec.comment })));
    if (rec.repeat) words.appendChild(el("span", "walk-tag walk-tag--again", tx("walk.rec.repeat")));
    b.appendChild(words);
    if (writable()) b.appendChild(el("span", "walk-rec__chev", "›"));
    row.appendChild(b);
    return row;
  }

  function zoneItems(zone) {
    return S.data.items.filter(function (i) {
      return !i.measure && (!i.zones.length || i.zones.indexOf(zone.code) !== -1);
    });
  }

  /** Сколько пунктов чек-листа видно сразу; остальное — по «Показать ещё» (D422). */
  var CL_LIMIT = 15;

  /** Чек-лист зоны: что здесь смотреть. Пункт — вход в запись по нему. */
  function renderChecklist(zone) {
    var items = zoneItems(zone);
    if (!items.length) return null;
    var was = {};
    zone.previous.forEach(function (p) { was[p.code] = true; });
    var rec = {};
    zone.recorded.forEach(function (r) { rec[r.code] = r; });
    items = items.filter(function (i) { return was[i.code]; }).concat(items.filter(function (i) { return !was[i.code]; }));

    var box = el("section", "walk-cl" + (S.list ? " is-open" : ""));
    var wrap = el("div", "walk-cl__wrap");
    wrap.inert = !S.list;
    var head = W.hinted(W.button("walk-cl__head", null, function () {
      S.list = !S.list;
      box.classList.toggle("is-open", S.list);
      head.setAttribute("aria-expanded", S.list ? "true" : "false");
      wrap.inert = !S.list;
    }), "checklist");
    head.setAttribute("aria-expanded", S.list ? "true" : "false");
    head.appendChild(el("span", "walk-cl__title", tx("walk.cl.title")));
    head.appendChild(el("span", "walk-cl__count", tx("walk.cl.count", { count: items.length })));
    head.appendChild(el("span", "walk-cl__caret", "▾"));
    box.appendChild(head);

    var inner = el("div", "walk-cl__inner");
    if (writable()) inner.appendChild(el("p", "walk-cl__hint", tx("walk.cl.hint")));
    var list = el("ul", "walk-cl__list");
    var rest = S.clAll === zone.code ? 0 : Math.max(0, items.length - CL_LIMIT);
    items.slice(0, items.length - rest).forEach(function (i) {
      var li = el("li");
      var done = rec[i.code];
      var b = W.button("walk-cl__item" + (done ? " is-recorded" : ""), null, function () {
        if (!writable()) return;
        if (done) W.sheet.open({ record: done, zone: zone.code });
        else W.sheet.open({ mode: "violation", zone: zone.code, code: i.code, level: i.levels.length === 1 ? i.levels[0] : null });
      });
      b.appendChild(el("span", "walk-cl__text", i.q));
      if (was[i.code]) b.appendChild(el("span", "walk-cl__was", tx("walk.cl.was")));
      b.appendChild(el("span", "walk-cl__act", done ? "✓" : "+"));
      li.appendChild(b);
      li.dataset.code = i.code;
      li.dataset.zone = zone.code;
      if (W.hints && W.hints.decorateChecklist) W.hints.decorateChecklist(li, { code: i.code, zone: zone.code, recorded: !!done });
      list.appendChild(li);
    });
    inner.appendChild(list);
    if (rest) {
      inner.appendChild(W.button("walk-cl__more", tx("walk.cl.more", { count: rest }), function () {
        S.clAll = zone.code;
        render();
      }));
    }
    wrap.appendChild(inner);
    box.appendChild(wrap);
    return box;
  }

  /** Остановка «Оборудование»: каждый замер методики — строкой; замер,
   *  привязанный к нескольким зонам (холодильник в двух шкафах), — строкой
   *  на зону. Нажатие открывает показание или форму замера уже с пунктом. */
  function renderEquipment(zone) {
    var box = el("section", "walk-ms");
    box.appendChild(el("p", "walk-stage__note", tx("walk.eq.hint")));
    var list = el("ul", "walk-ms__list");
    S.data.items.filter(function (i) { return i.measure; }).forEach(function (i) {
      (i.zones.length ? i.zones : [null]).forEach(function (target) {
        var got = zone.recorded.filter(function (r) { return r.code === i.code && (!target || r.zone === target); });
        var li = el("li");
        var b = W.button("walk-ms__item" + (got.length ? " is-done" : ""), null, function () {
          if (!writable()) return;
          if (got.length) W.sheet.open({ record: got[0], zone: got[0].zone });
          else W.sheet.open({ mode: "measure", zone: target, code: i.code, level: "D0" });
        });
        var words = el("span", "walk-ms__words");
        words.appendChild(el("span", "walk-ms__text", i.q));
        var where = target ? zoneTitle(target) : got.map(function (r) { return zoneTitle(r.zone); }).join(", ");
        if (where) words.appendChild(el("span", "walk-ms__zone", where));
        b.appendChild(words);
        b.appendChild(el("span", "walk-ms__value", got.length ? got.map(function (r) { return r.text; }).join("; ") : tx("walk.zone.measure_add")));
        li.appendChild(b);
        list.appendChild(li);
      });
    });
    box.appendChild(list);
    return box;
  }

  function renderStage(zone) {
    var stage = el("section", "walk-stage" + (S.dir > 0 ? " is-from-right" : S.dir < 0 ? " is-from-left" : ""));
    S.dir = 0;
    if (zone.equipment) {
      stage.appendChild(renderEquipment(zone));
      if (zoneDone(zone)) stage.appendChild(unmarkRow(zone));
      if (writable() && !allDone()) stage.appendChild(finishLink());
      return stage;
    }
    if (zone.previous.length) {
      stage.appendChild(el("h2", "walk-sub", tx("walk.zone.before")));
      var prev = el("ul", "walk-list");
      zone.previous.forEach(function (p) { prev.appendChild(renderPreviousItem(p, zone)); });
      stage.appendChild(prev);
    }
    var own = zone.recorded;
    if (own.length) {
      stage.appendChild(el("h2", "walk-sub", tx("walk.zone.now")));
      var now = el("ul", "walk-list walk-list--records");
      own.forEach(function (r) { now.appendChild(renderRecord(r, zone)); });
      stage.appendChild(now);
    } else if (!zone.previous.length && writable()) {
      if (zoneDone(zone)) stage.appendChild(el("p", "walk-stage__note", tx("walk.zone.clean_done")));
    }
    var unseen = W.unseenBlock(zone, writable());
    if (unseen) stage.appendChild(unseen);
    var list = renderChecklist(zone);
    if (list) stage.appendChild(list);

    var extra = el("div", "walk-stage__extra");
    if (writable()) {
      extra.appendChild(W.button("walk-link", "+ " + tx("walk.add.short_advice"), function () {
        W.sheet.open({ mode: "advice", zone: zone.code });
      }));
    }
    if (zoneDone(zone)) extra.appendChild(unmarkButton(zone));
    if (writable() && !allDone()) extra.appendChild(finishLink());
    if (extra.childNodes.length) stage.appendChild(extra);
    return stage;
  }

  function unmarkButton(zone) {
    return W.button("walk-link walk-link--quiet", tx("walk.zone.unmark"), function () {
      S.marks.z = toggle(S.marks.z, zone.code);
      saveMarks();
      render();
    });
  }

  function unmarkRow(zone) {
    var extra = el("div", "walk-stage__extra");
    extra.appendChild(unmarkButton(zone));
    return extra;
  }

  /* ── низ экрана: записать и дальше ─────────────────────────────────── */

  function markAndNext(zone) {
    // Прошлое замечание здесь не отмечено — зону не засчитываем: это ровно
    // то, что проверка обязана перепроверить, и забыть его дороже всего.
    if (openPrevious(zone)) {
      W.haptic("error");
      W.toast(tx("walk.zone.need_prev"), "warn");
      var prev = root.querySelector(".walk-item--prev");
      if (prev) {
        prev.scrollIntoView({ behavior: "smooth", block: "center" });
        prev.classList.add("is-flash");
      }
      return;
    }
    if (S.marks.z.indexOf(zone.code) === -1) S.marks.z = S.marks.z.concat([zone.code]);
    saveMarks();
    W.haptic("success");
    W.toast(tx("walk.zone.done_toast", { zone: zone.title }), "ok");
    var next = nextOpen(zone.code);
    if (next) go(next.code, 1);
    else render();
  }

  function allDone() { return S.data.zones.every(zoneDone); }

  /** Тихая ссылка «Завершить проверку» в конце зоны: вход виден, пока не все зоны осмотрены. */
  function finishLink() {
    return W.hinted(W.button("walk-link walk-link--quiet", tx("walk.finish.title"), W.finish.ask), "finish");
  }

  function renderDock(zone) {
    var dock = el("div", "walk-dock");
    var row = el("div", "walk-dock__row");
    var add = W.hinted(W.button("walk-mark walk-dock__add", null, function () {
      // Нарушение не привязано к зоне на экране (D445): зона — мягкая подсказка,
      // запись встанет в зону пункта и слов. На «Оборудовании» подсказки нет.
      W.sheet.open({ mode: "violation", hint: zone.equipment ? null : zone.code });
    }), "add");
    add.appendChild(W.icon("camera"));
    add.appendChild(el("span", null, "+ " + tx("walk.add.short")));
    row.appendChild(add);
    var next = nextOpen(zone.code);
    var label;
    var act;
    var finish = allDone();
    if (!zoneDone(zone)) {
      label = tx("walk.next.mark");
      act = function () { markAndNext(zone); };
    } else if (next) {
      label = tx("walk.next.go");
      act = function () { go(next.code, 1); };
    } else {
      // Все зоны осмотрены: главное действие — завершить (D422).
      label = tx("walk.finish.dock");
      act = W.finish.ask;
    }
    row.appendChild(W.hinted(W.button("walk-dock__next" + (finish ? " is-finish" : ""), label, act), finish ? "finish" : "next"));
    dock.appendChild(row);
    return dock;
  }

  /* ── сведения о визите: отдельный лист, вход — в шапке ─────────────── */

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
    input.id = "walk-info-" + field.code;
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

  function renderInfoFields(box) {
    box.appendChild(el("p", "walk-info__hint", tx("walk.info.hint")));
    S.data.info.forEach(function (field) {
      var row = el("div", "walk-info__field");
      var label = el("label", "walk-form__label", field.q);
      row.appendChild(label);
      var made = infoInput(field);
      if (made.input) label.htmlFor = made.input.id;
      row.appendChild(made.node);
      if (made.input && made.input.tagName === "TEXTAREA") {
        var bar = W.translateBar(made.input);
        if (bar) row.appendChild(bar);
      }
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
  }

  function onInfoBack() { closeInfo(); }

  function openInfo() {
    S.info = true;
    renderInfoSheet();
    if (W.supports("6.1")) {
      tg.BackButton.onClick(onInfoBack);
      tg.BackButton.show();
    }
  }

  function closeInfo() {
    S.info = false;
    renderInfoSheet();
    if (W.supports("6.1")) {
      tg.BackButton.offClick(onInfoBack);
      W.app.syncBack();
    }
    render();
  }

  function renderInfoSheet() {
    var old = document.getElementById("walk-info-sheet");
    if (old) old.parentNode.removeChild(old);
    if (!S.info) {
      if (!W.sheet.isOpen()) document.documentElement.classList.remove("has-sheet");
      return;
    }
    var node = el("div", "walk-sheet walk-sheet--info");
    node.id = "walk-info-sheet";
    node.setAttribute("role", "dialog");
    node.setAttribute("aria-modal", "true");
    var head = el("div", "walk-sheet__head");
    head.appendChild(el("h2", "walk-sheet__title", tx("walk.info.title")));
    var close = W.button("walk-sheet__close", "✕", closeInfo);
    close.setAttribute("aria-label", tx("walk.sheet.close"));
    head.appendChild(close);
    node.appendChild(head);
    var body = el("div", "walk-sheet__body");
    var box = el("section", "walk-info");
    renderInfoFields(box);
    body.appendChild(box);
    node.appendChild(body);
    document.body.appendChild(node);
    document.documentElement.classList.add("has-sheet");
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
    // Обход — раздел приложения (D373): всё остальное рисует walk-app.js.
    W.app.start();
    if (!W.app.showsWalk()) { W.app.render(root); W.hints.afterRender(); return; }
    var zones = S.data.zones;
    var zone = current();
    root.appendChild(renderTop(zones));
    var recovery = renderMarksRecovery();
    if (recovery) root.appendChild(recovery);
    if (zone) {
      root.appendChild(renderSwitch(zones, zone));
      root.appendChild(renderStage(zone));
      if (writable()) root.appendChild(renderDock(zone));
      renderZonesSheet(zones, zone);
    }
    if (S.info) renderInfoSheet();
    window.scrollTo(0, y);
    W.hints.afterRender();
  }

  function renderEmpty(title, text) {
    root.textContent = "";
    var box = el("section", "walk-empty");
    box.appendChild(el("h1", "walk-empty__title", title));
    if (text) box.appendChild(el("p", "walk-empty__text", text));
    if (W.inTelegram()) box.appendChild(W.button("walk-mark", tx("walk.back"), function () { tg.close(); }));
    root.appendChild(box);
  }

  W.render = render;
  W.openInfo = openInfo;

  /** Принять свежие данные с сервера (ответ на чтение или запись). */
  W.apply = function (body, keepSheet) {
    var first = !S.data || S.data.key !== body.key;
    if (first && S.data && W.sheet.isOpen()) W.sheet.close(true);
    S.data = body;
    S.data = withEquipment(body);
    if (first && W.offline && body.state === "active") W.offline.start();
    document.documentElement.lang = body.lang;
    if (body.state !== "active") { if (!keepSheet) W.sheet.close(true); render(); return; }
    if (first) loadMarks(body, function (m, recovery) { if (S.data.key !== body.key) return; S.recoveryMarks = recovery; S.marks = m; S.open = null; render(); });
    else render();
  };

  /* ── загрузка ──────────────────────────────────────────────────────── */

  function load() {
    // Пока открыта форма, данные под ней не меняются: перерисовка унесла бы
    // выбранный пункт из-под пальца. Свежие придут ответом на сохранение.
    if (W.sheet.isOpen() || S.info) return;
    // Без сети экран не затираем ошибкой: данные на нём свежие, кадры ждут связи (D442).
    if (navigator.onLine === false && S.data && S.data.zones) return;
    W.post(W.urls.data, (tg && tg.initData) || "", "text/plain")
      .then(function (res) {
        if (!res.ok) {
          S.data = { texts: (res.body && res.body.texts) || {} };
          // Отказ по роли (D420) приходит с текстом сервера — его и показать.
          renderEmpty((res.body && res.body.message) ||
            tx(res.body && res.body.error === "closed" ? "walk.closed" : "walk.error"));
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
    // Во весь экран (D392), без шапки клиента — только на телефоне: на
    // компьютере полный экран закрыл бы весь монитор. Bot API 8.0.
    if (W.supports("8.0") && tg.requestFullscreen && /^(ios|android)/.test(tg.platform || "")) {
      try { tg.requestFullscreen(); } catch (e) { /* старый клиент — остаётся развёрнутым */ }
    }
    // Прокрутка длинной формы вниз не должна сворачивать окно (Bot API 7.7).
    if (W.supports("7.7") && tg.disableVerticalSwipes) tg.disableVerticalSwipes();
    tg.onEvent("themeChanged", theme);
    // Аудитор вернулся из чата, где мог записать нарушение, — данные свежие.
    tg.onEvent("activated", load);
  }
  // Свайп влево-вправо по всему экрану — соседняя зона, как стрелки ‹ › (D422). Только явно
  // горизонтальный жест. Не считается, если начат в полосе, которая листается
  // вбок («Осталось»), в поле ввода, в открытом листе или меню.
  var SWIPE_MIN_PX = 60;
  var SWIPE_RATIO = 1.5;
  var SWIPE_SKIP = ".walk-hints, .walk-strip, input, textarea, select, [contenteditable], " +
    ".walk-sheet, .walk-zsheet, .walk-confirm";

  function scrollsSideways(node) {
    for (var n = node; n && n !== document.body && n !== document.documentElement; n = n.parentElement) {
      if (n.scrollWidth > n.clientWidth + 1 && /(auto|scroll)/.test(window.getComputedStyle(n).overflowX)) return true;
    }
    return false;
  }

  var touch = null;
  document.addEventListener("touchstart", function (e) {
    var t = e.touches[0];
    var ok = e.touches.length === 1 && !e.target.closest(SWIPE_SKIP) && !scrollsSideways(e.target);
    touch = ok ? { x: t.clientX, y: t.clientY } : null;
  }, { passive: true });
  document.addEventListener("touchcancel", function () { touch = null; }, { passive: true });
  document.addEventListener("touchend", function (e) {
    if (!touch || !S.data || !S.data.zones || !W.app.showsWalk() || W.sheet.isOpen() || S.info || S.panel) return;
    var t = e.changedTouches[0];
    var dx = t.clientX - touch.x;
    var dy = t.clientY - touch.y;
    touch = null;
    if (Math.abs(dx) < SWIPE_MIN_PX || Math.abs(dx) <= Math.abs(dy) * SWIPE_RATIO) return;
    var zones = S.data.zones;
    var at = zoneIndex(S.open);
    var n = zones.length;
    if (dx < 0) go(zones[(at + 1) % n].code, 1);
    else go(zones[(at - 1 + n) % n].code, -1);
  }, { passive: true });

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible" && S.data) load();
  });
  theme();
  load();
})();
