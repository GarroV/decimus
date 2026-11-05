/* Мини-апп обхода: пакетный ввод нарушений (прототип).
 *
 * Несколько кадров из галереи, к каждому слова (или голос); «Найти пункты» одним
 * вызовом подбирает пункт, зону и класс по каждой карточке параллельно
 * (`/tg/walk/batch`, то же, что одиночный поиск и проверка класса). Зону аудитор
 * называет в комментарии; не названа — зона экрана, и карточка так и подписана.
 *
 * Модель предлагает, фиксирует человек: карточка сохраняется молча только
 * когда всё решено — пункт, зона, класс и (если пункт был нарушением в прошлый
 * раз) ответ «то же самое?». Остальные ждут. Запись — обычным `op: add`
 * тем же адресом, что одиночная (журнал шагов и словарь работают сами); кадры
 * грузятся тем же механизмом, что в форме записи (сжатие, очередь без связи).
 */
(function () {
  "use strict";

  var W = window.DecimusWalk;
  var el = W.el;
  var tx = function (key, params) { return W.tx(key, params); };

  var MAX_CARDS = 12;
  var WORDS_MAX = 1000;
  var LEVELS_REPEAT = ["D1", "D2"];

  var b = null;
  var node = null;
  var seq = 0;
  var unregister = null;

  /* ── данные экрана ─────────────────────────────────────────────────── */

  function zones() { return (W.state.data.zones || []).filter(function (z) { return !z.equipment; }); }
  function zoneOf(code) { return zones().filter(function (z) { return z.code === code; })[0] || null; }
  function zoneTitle(code) { var z = zoneOf(code); return z ? z.title : code; }
  function itemOf(code) { return (W.state.data.items || []).filter(function (i) { return i.code === code; })[0] || null; }

  function recordedFor(code, zone) {
    var found = null;
    (W.state.data.zones || []).forEach(function (z) {
      (z.recorded || []).forEach(function (r) {
        if (!found && r.code === code && (r.zone || z.code) === zone && /^D[1-3]$/.test(r.level)) found = r;
      });
    });
    return found;
  }

  function previousFor(code, zone) {
    var z = zoneOf(zone);
    return (z && z.previous || []).filter(function (p) { return p.code === code; })[0] || null;
  }

  /* ── карточка ──────────────────────────────────────────────────────── */

  function newCard() {
    return { id: "c" + (++seq), photos: [], words: "", result: null, finding: false, dirty: false,
      saved: null, seen: "", itemOk: false, humanZone: null, humanCode: null, manualMode: false, manualLevel: null, repeat: null, error: "" };
  }

  function refs(card) { return card.photos.filter(function (p) { return p.state === "done"; }).map(function (p) { return p.ref; }); }
  function photosPending(card) { return card.photos.some(function (p) { return p.state !== "done"; }); }

  function code(card) { return card.result && card.result.code || null; }
  function zone(card) { return card.result && card.result.zone || null; }

  /** Класс карточки: предложенный моделью или выбранный человеком. */
  function levelOf(card) {
    var r = card.result;
    if (!r || r.status !== "found" || !r.class) return null;
    if (card.manualMode) return card.manualLevel;
    return r.class.status === "ready" ? r.class.level : null;
  }

  function classStatus(card) { return card.manualMode ? "manual" : "ready"; }

  function repeatAsked(card) {
    var level = levelOf(card);
    return !!(level && LEVELS_REPEAT.indexOf(level) !== -1 && code(card) && zone(card) && previousFor(code(card), zone(card)));
  }

  /** Та же пара «пункт + зона» в более ранней несохранённой карточке списка. */
  function duplicatedInBatch(card) {
    var at = b.cards.indexOf(card);
    return b.cards.slice(0, at).some(function (other) {
      return other.saved === null && levelOf(other) && code(other) === code(card) && zone(other) === zone(card);
    });
  }

  /** Что мешает записать карточку: ключ текста или null — готова. */
  function problem(card) {
    var r = card.result;
    if (card.saved !== null || card.finding) return "busy";
    if (!r) return "unsearched";
    if (card.dirty) return "dirty";
    if (photosPending(card)) return "photos";
    if (r.status !== "found") return r.status;
    if (r.photo_only && !card.itemOk) return "confirm";
    if (!levelOf(card)) return "class";
    if (repeatAsked(card) && card.repeat === null) return "repeat";
    if (recordedFor(code(card), zone(card))) return "recorded";
    if (duplicatedInBatch(card)) return "batch_dup";
    return null;
  }

  function ready(card) { return problem(card) === null; }

  /* ── кадры ─────────────────────────────────────────────────────────── */

  function batchKey() { return W.state.data.key + "_batch"; }

  function holder(entryId) {
    var hit = null;
    b.cards.forEach(function (c) {
      c.photos.forEach(function (p) { if (p.entryId === entryId) hit = p; });
    });
    return hit;
  }

  function addFiles(card, files) {
    files.forEach(function (file) {
      var p = { state: "uploading", own: true, url: URL.createObjectURL(file) };
      card.photos.push(p);
      send(card, p, file);
    });
    draw();
  }

  function send(card, p, file) {
    p.state = "uploading";
    var blob = p.blob ? Promise.resolve(p.blob) : W.photo.compress(file);
    blob.then(function (made) {
      p.blob = made;
      if (navigator.onLine === false) throw W.photo.offline();
      return W.photo.upload(made, b.run_id);
    }).then(function (ref) {
      if (!b) return;
      p.ref = ref;
      p.state = "done";
      W.photo.remember(ref, p.url);
      markDirtyOnPhotos(card);
      draw();
    }, function (err) {
      if (!b) return;
      if (err && (err.retryable || err.status === 409 || err.code === "run_changed") && p.blob) { park(p, file); return; }
      p.state = "failed";
      p.file = file;
      draw();
    });
  }

  /** Новый кадр у найденной карточки меняет факты: подбор надо повторить. */
  function markDirtyOnPhotos(card) { if (card.result && card.saved === null) card.dirty = true; }

  /** Не дошло из-за сети: кадр ждёт связи на телефоне и уйдёт сам (D442). */
  function park(p, file) {
    if (!W.offline.available()) { p.state = "failed"; p.file = file; draw(); return; }
    W.offline.put(batchKey(), "batch", p.blob, b.run_id).then(function (entry) {
      p.entryId = entry.id;
      p.state = "waiting";
      W.toast(tx("walk.offline.parked"), "warn");
      W.offline.kick();
      W.offline.watch();
      if (b) draw();
    }, function () {
      p.state = "failed";
      p.file = file;
      W.toast(tx("walk.offline.nostore"), "warn");
      if (b) draw();
    });
  }

  function adopt(entry, ref) {
    if (!b || entry.run_id !== b.run_id) return false;
    var p = holder(entry.id);
    if (!p) return false;
    p.ref = ref;
    p.state = "done";
    W.photo.remember(ref, p.url);
    b.cards.forEach(markDirtyOnPhotos);
    draw();
    return true;
  }

  function uploadFailed(entry) {
    var p = b && holder(entry.id);
    if (!p) return false;
    p.state = "failed";
    draw();
    return true;
  }

  function removePhoto(card, p) {
    card.photos = card.photos.filter(function (x) { return x !== p; });
    if (p.entryId) W.offline.remove(p.entryId);
    markDirtyOnPhotos(card);
    draw();
  }

  /* ── подбор ────────────────────────────────────────────────────────── */

  function find(list) {
    if (!list.length || b.busy) return;
    var payload = list.map(function (c) {
      return { id: c.id, words: c.words.trim(), photos: refs(c), code: c.humanCode || undefined, zone: c.humanZone || undefined };
    });
    var before = {};
    list.forEach(function (c) { before[c.id] = code(c) + "/" + zone(c); c.finding = true; c.error = ""; });
    b.busy = true;
    b.error = "";
    draw();
    W.post(W.urls.batch, { run_id: b.run_id, zone_hint: b.hint, cards: payload }).then(function (res) {
      if (!b) return;
      if (!res.ok || !res.body || !res.body.cards || res.body.run_id !== b.run_id) {
        throw new Error((res.body && res.body.message) || tx("walk.batch.find_failed"));
      }
      res.body.cards.forEach(function (r) {
        var c = list.filter(function (x) { return x.id === r.id; })[0];
        if (!c) return;
        c.result = r;
        c.dirty = false;
        c.manualMode = false;
        c.manualLevel = null;
        if (before[c.id] !== code(c) + "/" + zone(c)) c.repeat = null;
        c.seen = r.wording || (itemOf(r.code) || {}).q || "";
        c.itemOk = !!c.humanCode; // пункт, выбранный руками, подтверждён самим выбором
        if (r.status === "unavailable" && r.message) c.error = r.message;
      });
    }).catch(function (err) {
      if (b) b.error = err && err.message && err.message !== "Failed to fetch" ? err.message : tx("walk.batch.find_failed");
    }).then(function () {
      if (!b) return;
      list.forEach(function (c) { c.finding = false; });
      b.busy = false;
      draw();
    });
  }

  /** Карточек без комментария среди ещё не подобранных: по ним система смотрит только фото. */
  function bareCount() {
    return unsearched().filter(function (c) { return !c.words.trim(); }).length;
  }

  function unsearched() { return b.cards.filter(function (c) { return c.saved === null && !c.result && !c.finding; }); }

  /* ── запись ────────────────────────────────────────────────────────── */

  function textOf(card) {
    var r = card.result;
    var item = itemOf(r.code);
    return card.words.trim() || (r.photo_only && card.seen.trim()) || r.wording || (item && item.q) || r.code;
  }

  function addBody(card) {
    var r = card.result;
    var level = levelOf(card);
    var sug = r.suggested;
    return {
      op: "add", zone: r.zone, code: r.code, level: level, text: textOf(card), comment: "",
      repeat: card.repeat === true && LEVELS_REPEAT.indexOf(level) !== -1,
      photos: refs(card), photo_assignment: null, words: card.words.trim(),
      class_status: classStatus(card),
      suggested: sug ? { code: sug.code, level: sug.level, zone: sug.zone, confidence: sug.confidence, via: r.via } : null,
      reading_c: null, hint_codes: [],
    };
  }

  /** Одна запись за другой: падение одной не останавливает остальные. */
  function saveAll() {
    var list = b.cards.filter(ready);
    if (!list.length || b.saving) return;
    b.saving = true;
    b.error = "";
    var done = 0;
    var failed = 0;
    draw();
    var chain = list.reduce(function (p, card) {
      return p.then(function () {
        if (!b || !ready(card)) return;
        return W.api.write(W.urls.finding, addBody(card), b.run_id).then(function (res) {
          if (!res.ok || !res.body || res.body.run_id !== b.run_id) throw new Error((res.body && res.body.message) || tx("walk.error"));
          W.apply(res.body, true);
          card.saved = { n: null };
          card.error = "";
          done += 1;
          return acked(card);
        }).catch(function (err) {
          card.error = err && err.message && err.message !== "Failed to fetch" ? err.message : tx("walk.err.network");
          failed += 1;
        }).then(function () { if (b) draw(); });
      });
    }, Promise.resolve());
    chain.then(function () {
      if (!b) return;
      b.saving = false;
      if (done) { W.haptic("success"); W.toast(tx("walk.batch.saved_n", { n: done }), "ok"); }
      if (failed) W.haptic("error");
      draw();
    });
  }

  /** Кадры записанной карточки больше не нужны в хранилище телефона. */
  function acked(card) {
    var ids = card.photos.map(function (p) { return p.entryId; }).filter(Boolean);
    if (!ids.length || !W.offline.ack) return Promise.resolve();
    return W.offline.list(batchKey()).then(function (rows) {
      return W.offline.ack(batchKey(), b.run_id, rows.filter(function (r) { return ids.indexOf(r.id) !== -1; }).map(function (r) { return r.id; }));
    });
  }

  /** Такая запись уже есть: кадры карточки уходят к ней. */
  function attachTo(card, record) {
    if (b.saving) return;
    b.saving = true;
    draw();
    var chain = refs(card).reduce(function (p, ref) {
      return p.then(function () {
        return W.api.write(W.urls.finding, { op: "attach", n: record.n, ref: ref }, b.run_id).then(function (res) {
          if (!res.ok || !res.body || res.body.run_id !== b.run_id) throw new Error((res.body && res.body.message) || tx("walk.error"));
          W.apply(res.body, true);
        });
      });
    }, Promise.resolve());
    chain.then(function () {
      card.saved = { n: record.n };
      return acked(card);
    }).catch(function (err) {
      card.error = err && err.message && err.message !== "Failed to fetch" ? err.message : tx("walk.err.network");
    }).then(function () {
      if (!b) return;
      b.saving = false;
      draw();
    });
  }

  /* ── выбор пункта и зоны ───────────────────────────────────────────── */

  function pickItem(card) {
    W.menu.search({
      title: tx("walk.sheet.class_review.other_item"),
      placeholder: tx("walk.sheet.search"),
      list: function (query) {
        var terms = W.find.words(query);
        return (W.state.data.items || []).filter(function (i) {
          if (i.measure) return false;
          return !terms.length || W.find.allPrefix(terms, W.find.words(i.q + " " + (i.label || "") + " " + i.code + " " + i.process));
        }).slice(0, 60).map(function (i) {
          return { code: i.label, kind: "violation", label: i.q, value: i.code, terms: terms };
        });
      },
      onPick: function (value) {
        card.humanCode = value;
        card.humanZone = null;
        find([card]);
      },
    });
  }

  function pickZone(card) {
    var options = zones().map(function (z) { return { label: z.title, value: z.code, on: z.code === zone(card) }; });
    W.menu.open({
      title: tx("walk.batch.zone_pick"),
      options: options,
      onPick: function (value) {
        card.humanCode = code(card);
        card.humanZone = value;
        find([card]);
      },
    });
  }

  function chooseDeviation(card) {
    var item = itemOf(code(card));
    var levels = item ? item.levels : [];
    card.manualMode = true;
    card.manualLevel = levels.length === 1 ? levels[0] : null;
    draw();
  }

  /* ── разметка ──────────────────────────────────────────────────────── */

  function note(text, cls) { return el("p", "walk-form__hint" + (cls ? " " + cls : ""), text); }

  function zoneSource(r) {
    if (r.zone_source === "words") return tx("walk.batch.zone_words");
    if (r.zone_source === "human") return tx("walk.batch.zone_human");
    if (r.zone_source === "screen") return tx("walk.batch.zone_screen");
    if (r.zone_source === "ask") return tx("walk.batch.zone_ask");
    return tx("walk.batch.zone_item");
  }

  function levelPills(card) {
    var item = itemOf(code(card));
    var box = el("div", "walk-batch__levels");
    box.appendChild(el("span", "walk-form__hint", tx("walk.batch.level_pick")));
    (item ? item.levels : []).forEach(function (level) {
      var on = card.manualLevel === level;
      var pill = W.button("walk-btn walk-btn--small" + (on ? " is-on" : ""), level + " · " + tx("walk.sheet.class_review.level." + level), function () {
        card.manualLevel = level;
        draw();
      });
      pill.setAttribute("aria-pressed", String(on));
      box.appendChild(pill);
    });
    return box;
  }

  function classPart(card, box) {
    var c = card.result.class;
    if (card.manualMode) {
      if (card.manualLevel) box.appendChild(el("p", "walk-batch__class", tx("walk.sheet.class_review.manual_active")));
      box.appendChild(levelPills(card));
      return;
    }
    if (c.status === "ready") {
      var line = el("p", "walk-batch__class");
      line.appendChild(W.level(c.level));
      line.appendChild(document.createTextNode(" " + tx("walk.sheet.class_review.proposed", { level: c.level })));
      box.appendChild(line);
    } else if (c.status === "needs_fact") {
      box.appendChild(note(c.need_fact || ""));
      if (c.provisional_level) box.appendChild(note(tx("walk.sheet.class_review.provisional", { level: c.provisional_level })));
      box.appendChild(note(tx("walk.batch.fact_hint")));
      box.appendChild(W.button("walk-btn walk-btn--small", tx("walk.batch.retry"), function () { find([card]); }));
    } else {
      // Класс не установлен — те же два выхода, что в одиночном вводе (D711).
      box.appendChild(note(tx("walk.sheet.class_review.not_established")));
      var dead = el("div", "walk-deadend");
      var record = W.button("walk-btn walk-btn--primary", tx("walk.sheet.class_review.record_deviation"), function () { chooseDeviation(card); });
      record.setAttribute("data-batch-record", "");
      dead.appendChild(record);
      var other = W.button("walk-btn", tx("walk.sheet.class_review.other_item"), function () { pickItem(card); });
      other.setAttribute("data-batch-other", "");
      dead.appendChild(other);
      box.appendChild(dead);
    }
  }

  function repeatPart(card, box) {
    var prev = previousFor(code(card), zone(card));
    var date = W.state.data.previous ? W.day(W.state.data.previous.date) : "";
    var ask = el("div", "walk-batch__repeat");
    ask.setAttribute("data-batch-repeat", "");
    ask.appendChild(el("p", "walk-form__hint", tx("walk.batch.prev", { date: date, text: prev.text })));
    ask.appendChild(el("p", "walk-batch__ask", tx("walk.batch.prev_ask")));
    var row = el("div", "walk-batch__row");
    [[true, "walk.batch.prev_yes", "data-batch-repeat-yes"], [false, "walk.batch.prev_no", "data-batch-repeat-no"]].forEach(function (opt) {
      var on = card.repeat === opt[0];
      var button = W.button("walk-btn walk-btn--small" + (on ? " is-on" : ""), tx(opt[1]), function () {
        card.repeat = opt[0];
        draw();
      });
      button.setAttribute(opt[2], "");
      button.setAttribute("aria-pressed", String(on));
      row.appendChild(button);
    });
    ask.appendChild(row);
    box.appendChild(ask);
  }

  /** Только фото: что система увидела — пояснение, править необязательно («Найти заново» ищет по этим словам). */
  function seenPart(card, box) {
    var wrap = el("div", "walk-batch__seen");
    wrap.appendChild(el("p", "walk-form__hint", tx("walk.batch.seen")));
    var area = el("textarea", "walk-area walk-area--words");
    area.rows = 2;
    area.maxLength = WORDS_MAX;
    area.value = card.seen;
    area.setAttribute("data-batch-seen", card.id);
    area.addEventListener("input", function () { card.seen = area.value; });
    wrap.appendChild(area);
    var again = W.button("walk-btn walk-btn--small", tx("walk.batch.retry"), function () {
      if (!card.seen.trim()) return;
      card.words = card.seen.trim();
      find([card]);
    });
    again.setAttribute("data-batch-seen-again", "");
    wrap.appendChild(again);
    box.appendChild(wrap);
  }

  /** Только фото: пункт предложила система — без «Пункт верный» карточка не сохраняется. */
  function itemConfirm(card, box) {
    var row = el("div", "walk-batch__row");
    var ok = W.button("walk-btn walk-btn--small" + (card.itemOk ? " is-on" : ""), card.itemOk ? tx("walk.batch.item_ok_set") : tx("walk.batch.item_ok"), function () {
      card.itemOk = true;
      draw();
    });
    ok.setAttribute("data-batch-item-ok", "");
    ok.setAttribute("aria-pressed", String(card.itemOk));
    row.appendChild(ok);
    box.appendChild(row);
  }

  function resultPart(card) {
    var r = card.result;
    var box = el("div", "walk-batch__result");
    if (card.dirty) {
      box.appendChild(W.button("walk-btn walk-btn--small", tx("walk.batch.retry"), function () { find([card]); }));
      return box;
    }
    var tail = function (key) { box.appendChild(note(tx(key), "walk-form__hint--warn")); };
    if (r.status === "no_item") tail(r.photo_only ? "walk.batch.photo_none" : "walk.batch.no_item");
    else if (r.status === "unavailable" || r.status === "busy") box.appendChild(note(r.message || tx("walk.batch.unavailable"), "walk-form__hint--warn"));
    if (r.status === "no_item" || r.status === "unavailable" || r.status === "busy") {
      box.appendChild(W.button("walk-btn walk-btn--small", tx("walk.batch.retry"), function () { find([card]); }));
      box.appendChild(W.button("walk-btn walk-btn--small", tx("walk.sheet.class_review.other_item"), function () { pickItem(card); }));
      return box;
    }
    var item = itemOf(r.code);
    var head = el("p", "walk-batch__item");
    head.appendChild(el("strong", null, (item && item.label || r.code)));
    head.appendChild(document.createTextNode(" " + (item ? item.q : r.wording || "")));
    box.appendChild(head);
    if (r.photo_only && r.status !== "measure") seenPart(card, box);
    if (r.photo_only && (r.status === "found" || r.status === "need_zone")) itemConfirm(card, box);
    var where = el("p", "walk-batch__zone");
    where.setAttribute("data-batch-zone", r.zone || "");
    where.appendChild(document.createTextNode(r.zone ? tx("walk.batch.zone", { zone: zoneTitle(r.zone) }) + " — " + zoneSource(r) : zoneSource(r)));
    box.appendChild(where);
    var row = el("div", "walk-batch__row");
    row.appendChild(W.button("walk-link", tx("walk.batch.zone_change"), function () { pickZone(card); }));
    row.appendChild(W.button("walk-link", tx("walk.sheet.class_review.other_item"), function () { pickItem(card); }));
    box.appendChild(row);
    if (r.status === "measure") { tail("walk.batch.measure"); return box; }
    if (r.status === "no_facts") { tail("walk.batch.no_facts"); box.appendChild(W.button("walk-btn walk-btn--small", tx("walk.batch.retry"), function () { find([card]); })); return box; }
    if (r.status === "need_zone") { tail("walk.batch.zone_ask"); return box; }
    classPart(card, box);
    if (levelOf(card) && repeatAsked(card)) repeatPart(card, box);
    var record = levelOf(card) && recordedFor(r.code, r.zone);
    if (record) {
      box.appendChild(note(tx("walk.batch.dup_recorded", { n: record.n }), "walk-form__hint--warn"));
      if (refs(card).length) box.appendChild(W.button("walk-btn walk-btn--small", tx("walk.batch.dup_attach"), function () { attachTo(card, record); }));
    } else if (levelOf(card) && duplicatedInBatch(card)) {
      tail("walk.batch.dup_batch");
    }
    return box;
  }

  function stateBadge(card) {
    if (card.saved !== null) return el("span", "walk-batch__badge is-saved", tx("walk.batch.saved"));
    if (!card.result || card.finding) return null;
    return ready(card) ? el("span", "walk-batch__badge is-ready", tx("walk.batch.ready")) : el("span", "walk-batch__badge is-doubt", tx("walk.batch.doubt"));
  }

  function drawCard(card, index) {
    var li = el("li", "walk-batch__card");
    li.setAttribute("data-batch-card", card.id);
    if (card.saved !== null) li.classList.add("is-saved");
    else if (card.result && !card.finding) li.classList.add(ready(card) ? "is-ready" : "is-doubt");
    var head = el("div", "walk-batch__head");
    head.appendChild(el("span", "walk-batch__n", tx("walk.batch.card", { n: index + 1 })));
    var badge = stateBadge(card);
    if (badge) head.appendChild(badge);
    if (card.saved === null && !b.saving) {
      var drop = W.button("walk-batch__drop", "✕", function () {
        card.photos.forEach(function (p) { if (p.entryId) W.offline.remove(p.entryId); });
        b.cards = b.cards.filter(function (c) { return c !== card; });
        draw();
      });
      drop.setAttribute("aria-label", tx("walk.batch.drop"));
      head.appendChild(drop);
    }
    li.appendChild(head);

    if (card.saved !== null) {
      var strip = el("div", "walk-strip");
      card.photos.forEach(function (p) {
        var cell = el("div", "walk-strip__cell is-done");
        cell.appendChild(W.photo.thumb(p));
        strip.appendChild(cell);
      });
      li.appendChild(strip);
      li.appendChild(note(card.saved.n ? tx("walk.batch.saved_to", { n: card.saved.n }) : (itemOf(code(card)) || {}).q || ""));
      return li;
    }

    li.appendChild(W.photo.block(card.photos, {
      hero: false,
      onFiles: function (files) { addFiles(card, files); },
      onRetry: function (p) { send(card, p, p.file); draw(); },
      onRemove: function (p) { removePhoto(card, p); },
    }));
    var area = el("textarea", "walk-area walk-area--words");
    area.rows = 2;
    area.maxLength = WORDS_MAX;
    area.placeholder = tx("walk.batch.words_hint");
    area.value = card.words;
    area.disabled = card.finding;
    area.setAttribute("data-batch-words", card.id);
    var sync = function () {
      var was = card.dirty;
      card.words = area.value;
      if (card.result) card.dirty = true;
      if (was !== card.dirty || (b.bare !== undefined && b.bare !== bareCount())) draw();
    };
    area.addEventListener("input", sync);
    li.appendChild(area);
    var voice = W.voiceBar && W.voiceBar(area, sync);
    if (voice) li.appendChild(voice);
    if (card.finding) li.appendChild(note(tx("walk.batch.finding")));
    else if (card.result) li.appendChild(resultPart(card));
    if (card.error) li.appendChild(note(card.error, "walk-form__hint--warn"));
    return li;
  }

  function pickInput() {
    var label = el("label", "walk-btn walk-btn--primary walk-batch__pick");
    var input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.multiple = true;
    input.className = "walk-pick__input";
    input.setAttribute("data-batch-input", "");
    input.addEventListener("change", function () {
      var files = Array.prototype.slice.call(input.files || []);
      input.value = "";
      var room = MAX_CARDS - b.cards.length;
      if (files.length > room) W.toast(tx("walk.batch.limit", { n: MAX_CARDS }), "warn");
      files.slice(0, Math.max(room, 0)).forEach(function (file) {
        var card = newCard();
        b.cards.push(card);
        addFiles(card, [file]);
      });
      draw();
    });
    label.appendChild(W.icon("gallery", "walk-pick__icon"));
    label.appendChild(el("span", null, b.cards.length ? tx("walk.batch.pick_more") : tx("walk.batch.pick")));
    label.appendChild(input);
    return label;
  }

  function footer() {
    var foot = el("div", "walk-sheet__foot");
    var open = b.cards.filter(function (c) { return c.saved === null; });
    var pending = unsearched();
    var good = b.cards.filter(ready);
    var left = open.length - good.length;
    if (b.error) foot.appendChild(note(b.error, "walk-form__hint--warn"));
    var searched = b.cards.some(function (c) { return c.result; });
    if (searched && left > 0 && good.length) foot.appendChild(note(tx("walk.batch.waiting_n", { n: left })));
    if (pending.length) {
      var bare = bareCount();
      b.bare = bare;
      if (bare) {
        var warn = note(tx("walk.batch.photo_warn", { n: bare }), "walk-form__hint--warn");
        warn.setAttribute("data-batch-photo-warn", "");
        foot.appendChild(warn);
      }
      var blocked = pending.some(photosPending);
      var go = W.button("walk-mark", b.busy ? tx("walk.batch.finding") : tx("walk.batch.find"), function () { find(unsearched()); });
      go.setAttribute("data-batch-find", "");
      go.disabled = b.busy || b.saving || blocked;
      foot.appendChild(go);
      if (blocked) foot.appendChild(el("p", "walk-sheet__why", tx("walk.batch.need_photos")));
    }
    if (searched) {
      var save = W.button("walk-mark" + (pending.length ? " walk-batch__second" : ""), b.saving ? tx("walk.batch.saving") : tx("walk.batch.save_ready", { n: good.length }), saveAll);
      save.setAttribute("data-batch-save", "");
      save.disabled = !good.length || b.saving || b.busy;
      foot.appendChild(save);
    }
    if (!pending.length && !searched && !b.cards.length) foot.appendChild(el("p", "walk-sheet__why", tx("walk.batch.need_cards")));
    return foot;
  }

  function draw() {
    if (!b || !node) return;
    var active = document.activeElement;
    var focusAttr = active && active.getAttribute && (active.getAttribute("data-batch-words") ? "data-batch-words" : active.getAttribute("data-batch-seen") ? "data-batch-seen" : null);
    var focusId = focusAttr && active.getAttribute(focusAttr);
    var from = active && active.selectionStart;
    var scroller = node.querySelector(".walk-sheet__body");
    var top = scroller ? scroller.scrollTop : 0;
    node.textContent = "";
    var head = el("div", "walk-sheet__head");
    head.appendChild(el("h2", "walk-sheet__title", tx("walk.batch.title")));
    var x = W.button("walk-sheet__close", "✕", close);
    x.setAttribute("aria-label", tx("walk.batch.close"));
    head.appendChild(x);
    node.appendChild(head);
    var body = el("div", "walk-sheet__body");
    if (!b.cards.length) body.appendChild(note(tx("walk.batch.intro")));
    body.appendChild(pickInput());
    var list = el("ol", "walk-batch__list");
    b.cards.forEach(function (card, index) { list.appendChild(drawCard(card, index)); });
    body.appendChild(list);
    node.appendChild(body);
    node.appendChild(footer());
    body.scrollTop = top;
    if (focusId) {
      var again = node.querySelector('[' + focusAttr + '="' + focusId + '"]');
      if (again) { again.focus(); if (from != null) again.setSelectionRange(from, from); }
    }
  }

  /* ── вход и выход ──────────────────────────────────────────────────── */

  function open(hint) {
    if (b || !W.state.data || W.state.data.state !== "active") return;
    b = { hint: hint || null, cards: [], busy: false, saving: false, error: "", run_id: W.state.data.run_id };
    node = el("div", "walk-sheet walk-batch");
    node.setAttribute("role", "dialog");
    node.setAttribute("aria-modal", "true");
    document.body.appendChild(node);
    document.documentElement.classList.add("has-sheet");
    unregister = W.offline.register(batchKey(), { uploaded: adopt, failed: uploadFailed });
    draw();
  }

  function close() {
    if (!b || b.saving) return;
    b.cards.forEach(function (card) {
      if (card.saved !== null) return;
      card.photos.forEach(function (p) { if (p.entryId) W.offline.remove(p.entryId); });
    });
    if (unregister) unregister();
    unregister = null;
    node.remove();
    node = null;
    b = null;
    document.documentElement.classList.remove("has-sheet");
  }

  W.batch = { open: open, close: close, isOpen: function () { return !!b; } };
})();
