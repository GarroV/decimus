/* Мини-апп обхода: пакетный ввод нарушений.
 *
 * До 5 кадров из галереи (карточек), к каждому слова (или голос); «Найти пункты» одним
 * вызовом подбирает пункт, зону и класс (`/tg/walk/batch`, то же, что одиночный поиск и
 * проверка класса). Зону аудитор называет в комментарии; не названа — зона экрана.
 *
 * С одного кадра — несколько нарушений (D713): карточка = кадры + список СТРОК. Комментарий
 * с разными дефектами сервер делит на строки; кадр без слов — строка на каждое увиденное
 * нарушение; «+ ещё нарушение на этом фото» добавляет строку руками. У каждой строки свой
 * пункт, зона, класс, вопрос о повторе; запись — отдельная на каждую, кадры карточки
 * прикладываются ссылкой к каждой.
 *
 * Модель предлагает, фиксирует человек: строка сохраняется молча только когда всё решено —
 * пункт, зона, класс, (если пункт нашла система по кадру без слов — «Пункт верный») и (если
 * пункт был нарушением в прошлый раз) ответ «то же самое?». Остальные ждут. Запись — обычным
 * `op: add` тем же адресом, что одиночная (журнал шагов и словарь работают сами); кадры
 * грузятся тем же механизмом, что в форме записи (сжатие, очередь без связи).
 */
(function () {
  "use strict";

  var W = window.DecimusWalk;
  var el = W.el;
  var tx = function (key, params) { return W.tx(key, params); };

  var MAX_CARDS = 5;
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

  /* ── карточка и строка ─────────────────────────────────────────────── */

  /* Карточка — кадры и слова. Строка — одно нарушение на этих кадрах: свой пункт, зона, класс. */
  function newCard() {
    return { id: "c" + (++seq), photos: [], words: "", lines: [], state: "new", dirty: false, finding: false, error: "", splitFailed: false, humanZone: null };
  }

  function newLine(card, id, manual) {
    return { id: id || ("l" + (++seq)), card: card, words: "", result: null, saved: null, seen: "", itemOk: false,
      humanZone: null, humanCode: null, manualMode: false, manualLevel: null, repeat: null, distinct: false,
      finding: false, manual: !!manual, error: "" };
  }

  function refs(card) { return card.photos.filter(function (p) { return p.state === "done"; }).map(function (p) { return p.ref; }); }
  function photosPending(card) { return card.photos.some(function (p) { return p.state !== "done"; }); }

  function code(line) { return line.result && line.result.code || null; }
  function zone(line) { return line.result && line.result.zone || null; }

  /** Класс строки: предложенный моделью или выбранный человеком. */
  function levelOf(line) {
    var r = line.result;
    if (!r || r.status !== "found" || !r.class) return null;
    if (line.manualMode) return line.manualLevel;
    return r.class.status === "ready" ? r.class.level : null;
  }

  function classStatus(line) { return line.manualMode ? "manual" : "ready"; }

  function repeatAsked(line) {
    var level = levelOf(line);
    return !!(level && LEVELS_REPEAT.indexOf(level) !== -1 && code(line) && zone(line) && previousFor(code(line), zone(line)));
  }

  function allLines() {
    return b.cards.reduce(function (all, card) { return all.concat(card.lines); }, []);
  }

  /** Та же пара «пункт + зона» в более ранней несохранённой строке списка. */
  function duplicatedInBatch(line) {
    var all = allLines();
    return all.slice(0, all.indexOf(line)).some(function (other) {
      return other.saved === null && levelOf(other) && code(other) === code(line) && zone(other) === zone(line);
    });
  }

  /** Система нашла пункт по кадру без слов: без «Пункт верный» строка не сохраняется (D713). */
  function needsApproval(line) { return !!(line.result && line.result.photo_only); }

  /** Что мешает записать строку: ключ текста или null — готова. */
  function problem(line) {
    var r = line.result;
    if (line.saved !== null || line.finding || line.card.finding) return "busy";
    if (!r) return "unsearched";
    if (line.card.dirty) return "dirty";
    if (photosPending(line.card)) return "photos";
    if (r.status !== "found") return r.status;
    if (needsApproval(line) && !line.itemOk) return "confirm";
    if (!levelOf(line)) return "class";
    if (repeatAsked(line) && line.repeat === null) return "repeat";
    if (recordedFor(code(line), zone(line)) && !line.distinct) return "recorded";
    if (duplicatedInBatch(line)) return "batch_dup";
    return null;
  }

  function ready(line) { return problem(line) === null; }

  function openLines(card) { return card.lines.filter(function (l) { return l.saved === null; }); }
  function hasSaved(card) { return card.lines.some(function (l) { return l.saved !== null; }); }

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
  function markDirtyOnPhotos(card) { if (card.state !== "new" && !hasSaved(card)) card.dirty = true; }

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

  /** Строка из ответа сервера: решение человека (пункт, зона) переносится, прежний повтор сбрасывается при смене пары. */
  function fill(line, r, before) {
    line.result = r;
    line.manualMode = false;
    line.manualLevel = null;
    if (before !== code(line) + "/" + zone(line)) { line.repeat = null; line.distinct = false; }
    line.seen = r.wording || (itemOf(r.code) || {}).q || "";
    line.itemOk = !!line.humanCode; // пункт, выбранный руками, подтверждён самим выбором
    if (r.status === "unavailable" && r.message) line.error = r.message;
  }

  function begin(list) {
    b.busy = true;
    b.error = "";
    list.forEach(function (x) { x.finding = true; x.error = ""; });
    draw();
  }

  function finish(list) {
    if (!b) return;
    list.forEach(function (x) { x.finding = false; });
    b.busy = false;
    draw();
  }

  function failed(err) {
    if (b) b.error = err && err.message && err.message !== "Failed to fetch" ? err.message : tx("walk.batch.find_failed");
  }

  function request(cards) {
    return W.post(W.urls.batch, { run_id: b.run_id, zone_hint: b.hint, cards: cards }).then(function (res) {
      if (!res.ok || !res.body || !res.body.cards || res.body.run_id !== b.run_id) {
        throw new Error((res.body && res.body.message) || tx("walk.batch.find_failed"));
      }
      return res.body.cards;
    });
  }

  /** Карточки целиком: слова делятся на строки, кадр без слов — на всё увиденное. Сохранённые и ручные строки остаются. */
  function find(list) {
    if (!list.length || b.busy) return;
    var payload = list.map(function (c) {
      return { id: c.id, words: c.words.trim(), photos: refs(c), card_zone: c.humanZone || undefined };
    });
    begin(list);
    request(payload).then(function (answers) {
      if (!b) return;
      answers.forEach(function (a) {
        var card = list.filter(function (x) { return x.id === a.id; })[0];
        if (!card) return;
        var kept = card.lines.filter(function (l) { return l.saved !== null || l.manual; });
        card.dirty = false;
        card.splitFailed = !!a.split_failed;
        card.state = a.status === "ok" ? "found" : "failed";
        card.error = a.status === "ok" ? "" : (a.message || tx("walk.batch.unavailable"));
        var fresh = (a.lines || []).map(function (r) {
          var line = newLine(card, r.id);
          line.words = r.words || "";
          fill(line, r, null);
          return line;
        });
        // Порядок: записанные, найденные системой, затем добавленные руками и ещё не записанные.
        card.lines = kept.filter(function (l) { return l.saved !== null; })
          .concat(fresh, kept.filter(function (l) { return l.saved === null; }));
      });
    }).catch(failed).then(function () {
      finish(list);
      if (list.length > 1) toFirstCard();
    });
  }

  /** Одна строка заново: после выбора пункта или зоны, дописанных слов («Найти заново»). Остальные строки не трогаются. */
  function findLine(line) {
    if (b.busy) return;
    var card = line.card;
    var payload = { id: card.id, line: line.id, words: line.words.trim(), photos: refs(card),
      photo_only: !!(line.result && line.result.photo_only) && !line.words.trim(),
      code: line.humanCode || undefined, zone: line.humanZone || card.humanZone || undefined };
    var before = code(line) + "/" + zone(line);
    begin([line]);
    request([payload]).then(function (answers) {
      if (!b) return;
      var a = answers[0];
      var r = a && a.lines && a.lines[0];
      if (!r) throw new Error((a && a.message) || tx("walk.batch.find_failed"));
      fill(line, r, before);
    }).catch(failed).then(function () { finish([line]); });
  }

  /** Результаты по всей пачке выросли над и под экраном: показываем с первой карточки, а не с середины списка. */
  function toFirstCard() {
    var scroller = node && node.querySelector(".walk-sheet__body");
    var first = scroller && scroller.querySelector("[data-batch-card]");
    if (first) scroller.scrollTop += first.getBoundingClientRect().top - scroller.getBoundingClientRect().top - 8;
  }

  /** Карточек без комментария среди ещё не подобранных: по ним система смотрит только фото. */
  function bareCount() {
    return unsearched().filter(function (c) { return !c.words.trim(); }).length;
  }

  function unsearched() { return b.cards.filter(function (c) { return c.state === "new" && !c.finding; }); }

  /** «+ ещё нарушение на этом фото»: пустая строка, слова пишет человек, пункт ищет система. */
  function addLine(card) {
    var line = newLine(card, null, true);
    card.lines.push(line);
    draw();
    var area = node && node.querySelector('[data-batch-line-words="' + line.id + '"]');
    if (area) area.focus();
  }

  function dropLine(line) {
    line.card.lines = line.card.lines.filter(function (l) { return l !== line; });
    draw();
  }

  /* ── запись ────────────────────────────────────────────────────────── */

  /* «Зафиксировано» — как в обычном вводе: формулировка модели (по кадру — её же текст «что видно»,
     который аудитор мог поправить), она на языке чек-листа (= язык
     отчёта). Сырые слова аудитора туда не идут: они на языке речи, и автоперевод (D443) их не
     переводит — 06.11.2026 записи пакета ушли в английский отчёт по-русски. */
  function textOf(line) {
    var r = line.result;
    var item = itemOf(r.code);
    return (r.photo_only && line.seen.trim()) || r.wording || (item && item.q) || r.code;
  }

  /* Формулировки модели нет (пункт выбран руками): слова аудитора — комментарием, его переводит
     автоперевод и кнопка в вычитке. Есть формулировка — она уже пересказывает те же слова. */
  function commentOf(line) {
    return line.result.wording ? "" : line.words.trim();
  }

  function addBody(line) {
    var r = line.result;
    var level = levelOf(line);
    var sug = r.suggested;
    return {
      op: "add", zone: r.zone, code: r.code, level: level, text: textOf(line), comment: commentOf(line),
      repeat: line.repeat === true && LEVELS_REPEAT.indexOf(level) !== -1,
      // Кадры карточки уходят ссылкой в каждую запись строки: файл один, записей несколько.
      photos: refs(line.card), photo_assignment: null, words: line.words.trim(),
      class_status: classStatus(line),
      suggested: sug ? { code: sug.code, level: sug.level, zone: sug.zone, confidence: sug.confidence, via: r.via } : null,
      reading_c: null, hint_codes: [],
    };
  }

  /** Одна запись за другой: падение одной не останавливает остальные. */
  function saveAll() {
    var list = allLines().filter(ready);
    if (!list.length || b.saving) return;
    b.saving = true;
    b.error = "";
    var done = 0;
    var bad = 0;
    draw();
    var chain = list.reduce(function (p, line) {
      return p.then(function () {
        if (!b || !ready(line)) return;
        return W.api.write(W.urls.finding, addBody(line), b.run_id).then(function (res) {
          if (!res.ok || !res.body || res.body.run_id !== b.run_id) throw new Error((res.body && res.body.message) || tx("walk.error"));
          W.apply(res.body, true);
          line.saved = { n: null };
          line.error = "";
          done += 1;
          return acked(line.card);
        }).catch(function (err) {
          line.error = err && err.message && err.message !== "Failed to fetch" ? err.message : tx("walk.err.network");
          bad += 1;
        }).then(function () { if (b) draw(); });
      });
    }, Promise.resolve());
    chain.then(function () {
      if (!b) return;
      b.saving = false;
      if (done) { W.haptic("success"); W.toast(tx("walk.batch.saved_n", { n: done }), "ok"); }
      if (bad) W.haptic("error");
      draw();
    });
  }

  /** Кадры записанной строки больше не нужны в хранилище телефона. */
  function acked(card) {
    var ids = card.photos.map(function (p) { return p.entryId; }).filter(Boolean);
    if (!ids.length || !W.offline.ack) return Promise.resolve();
    return W.offline.list(batchKey()).then(function (rows) {
      return W.offline.ack(batchKey(), b.run_id, rows.filter(function (r) { return ids.indexOf(r.id) !== -1; }).map(function (r) { return r.id; }));
    });
  }

  /** Такая запись уже есть: кадры карточки уходят к ней. */
  function attachTo(line, record) {
    if (b.saving) return;
    b.saving = true;
    draw();
    var chain = refs(line.card).reduce(function (p, ref) {
      return p.then(function () {
        return W.api.write(W.urls.finding, { op: "attach", n: record.n, ref: ref }, b.run_id).then(function (res) {
          if (!res.ok || !res.body || res.body.run_id !== b.run_id) throw new Error((res.body && res.body.message) || tx("walk.error"));
          W.apply(res.body, true);
        });
      });
    }, Promise.resolve());
    chain.then(function () {
      line.saved = { n: record.n };
      return acked(line.card);
    }).catch(function (err) {
      line.error = err && err.message && err.message !== "Failed to fetch" ? err.message : tx("walk.err.network");
    }).then(function () {
      if (!b) return;
      b.saving = false;
      draw();
    });
  }

  /* ── выбор пункта и зоны ───────────────────────────────────────────── */

  function pickItem(line) {
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
        line.humanCode = value;
        line.humanZone = null;
        findLine(line);
      },
    });
  }

  function pickZone(line) {
    var options = zones().map(function (z) { return { label: z.title, value: z.code, on: z.code === zone(line) }; });
    W.menu.open({
      title: tx("walk.batch.zone_pick"),
      options: options,
      onPick: function (value) {
        line.humanCode = code(line);
        line.humanZone = value;
        // Зона, выбранная руками, держится за карточкой: повторный подбор её не сбрасывает.
        line.card.humanZone = value;
        findLine(line);
      },
    });
  }

  function chooseDeviation(line) {
    var item = itemOf(code(line));
    var levels = item ? item.levels : [];
    line.manualMode = true;
    line.manualLevel = levels.length === 1 ? levels[0] : null;
    draw();
  }

  /* ── разметка строки ───────────────────────────────────────────────── */

  function note(text, cls) { return el("p", "walk-form__hint" + (cls ? " " + cls : ""), text); }

  function zoneSource(r) {
    if (r.zone_source === "words") return tx("walk.batch.zone_words");
    if (r.zone_source === "human") return tx("walk.batch.zone_human");
    if (r.zone_source === "hint" || r.zone_source === "screen") return tx("walk.batch.zone_screen");
    if (r.zone_source === "ask") return tx("walk.batch.zone_ask");
    return tx("walk.batch.zone_item");
  }

  function levelPills(line) {
    var item = itemOf(code(line));
    var box = el("div", "walk-batch__levels");
    box.appendChild(el("span", "walk-form__hint", tx("walk.batch.level_pick")));
    (item ? item.levels : []).forEach(function (level) {
      var on = line.manualLevel === level;
      var pill = W.button("walk-btn walk-btn--small" + (on ? " is-on" : ""), W.levelWord(level), function () {
        line.manualLevel = level;
        draw();
      });
      pill.setAttribute("aria-pressed", String(on));
      box.appendChild(pill);
    });
    return box;
  }

  function classPart(line, box) {
    var c = line.result.class;
    if (line.manualMode) {
      if (line.manualLevel) box.appendChild(el("p", "walk-batch__class", tx("walk.sheet.class_review.manual_active")));
      box.appendChild(levelPills(line));
      return;
    }
    if (c.status === "ready") {
      var text = el("p", "walk-batch__class");
      text.appendChild(W.level(c.level));
      text.appendChild(document.createTextNode(" " + tx("walk.sheet.class_review.proposed", { level: c.level })));
      box.appendChild(text);
    } else if (c.status === "needs_fact") {
      box.appendChild(note(c.need_fact || ""));
      if (c.provisional_level) box.appendChild(note(tx("walk.sheet.class_review.provisional", { level: c.provisional_level })));
      box.appendChild(note(tx("walk.batch.fact_hint")));
      box.appendChild(W.button("walk-btn walk-btn--small", tx("walk.batch.retry"), function () { findLine(line); }));
    } else {
      // Класс не установлен — те же два выхода, что в одиночном вводе (D711).
      box.appendChild(note(tx("walk.sheet.class_review.not_established")));
      var dead = el("div", "walk-deadend");
      var record = W.button("walk-btn walk-btn--primary", tx("walk.sheet.class_review.record_deviation"), function () { chooseDeviation(line); });
      record.setAttribute("data-batch-record", "");
      dead.appendChild(record);
      var other = W.button("walk-btn", tx("walk.sheet.class_review.other_item"), function () { pickItem(line); });
      other.setAttribute("data-batch-other", "");
      dead.appendChild(other);
      box.appendChild(dead);
    }
  }

  /** Пункт уже записан в этой зоне: показать прежний кадр и слова, спросить «то же или другое». */
  function sameOrOther(line, box, record) {
    var ask = el("div", "walk-batch__same");
    ask.setAttribute("data-batch-same", "");
    ask.appendChild(note(tx("walk.batch.dup_recorded", { n: record.n }), "walk-form__hint--warn"));
    var shown = el("div", "walk-batch__row");
    var shot = (record.photos || [])[0];
    if (shot) shown.appendChild(W.photo.thumb(shot));
    var said = (record.words || record.text || "").trim();
    if (said) shown.appendChild(el("span", "walk-form__hint", said));
    if (shot || said) ask.appendChild(shown);
    ask.appendChild(el("p", "walk-batch__ask", tx("walk.batch.dup_ask")));
    var row = el("div", "walk-batch__row");
    if (refs(line.card).length) {
      var same = W.button("walk-btn walk-btn--small", tx("walk.batch.dup_attach"), function () { attachTo(line, record); });
      same.setAttribute("data-batch-same-yes", "");
      row.appendChild(same);
    }
    var other = W.button("walk-btn walk-btn--small" + (line.distinct ? " is-on" : ""), tx("walk.batch.dup_other"), function () {
      line.distinct = true;
      draw();
    });
    other.setAttribute("data-batch-same-no", "");
    other.setAttribute("aria-pressed", String(!!line.distinct));
    row.appendChild(other);
    ask.appendChild(row);
    box.appendChild(ask);
  }

  function repeatPart(line, box) {
    var prev = previousFor(code(line), zone(line));
    var date = W.state.data.previous ? W.day(W.state.data.previous.date) : "";
    var ask = el("div", "walk-batch__repeat");
    ask.setAttribute("data-batch-repeat", "");
    ask.appendChild(el("p", "walk-form__hint", tx("walk.batch.prev", { date: date, text: prev.text })));
    ask.appendChild(el("p", "walk-batch__ask", tx("walk.batch.prev_ask")));
    var row = el("div", "walk-batch__row");
    [[true, "walk.batch.prev_yes", "data-batch-repeat-yes"], [false, "walk.batch.prev_no", "data-batch-repeat-no"]].forEach(function (opt) {
      var on = line.repeat === opt[0];
      var button = W.button("walk-btn walk-btn--small" + (on ? " is-on" : ""), tx(opt[1]), function () {
        line.repeat = opt[0];
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
  function seenPart(line, box) {
    var wrap = el("div", "walk-batch__seen");
    wrap.appendChild(el("p", "walk-form__hint", tx("walk.batch.seen")));
    var area = el("textarea", "walk-area walk-area--words");
    area.rows = 2;
    area.maxLength = WORDS_MAX;
    area.value = line.seen;
    area.setAttribute("data-batch-seen", line.id);
    area.addEventListener("input", function () { line.seen = area.value; });
    wrap.appendChild(area);
    var again = W.button("walk-btn walk-btn--small", tx("walk.batch.retry"), function () {
      if (!line.seen.trim()) return;
      line.words = line.seen.trim();
      findLine(line);
    });
    again.setAttribute("data-batch-seen-again", "");
    wrap.appendChild(again);
    box.appendChild(wrap);
  }

  /** Пункт нашла система по кадру без слов — без «Пункт верный» строка не сохраняется. */
  function itemConfirm(line, box) {
    var row = el("div", "walk-batch__row");
    var ok = W.button("walk-btn walk-btn--small" + (line.itemOk ? " is-on" : ""), line.itemOk ? tx("walk.batch.item_ok_set") : tx("walk.batch.item_ok"), function () {
      line.itemOk = true;
      draw();
    });
    ok.setAttribute("data-batch-item-ok", "");
    ok.setAttribute("aria-pressed", String(line.itemOk));
    row.appendChild(ok);
    box.appendChild(row);
  }

  function resultPart(line) {
    var r = line.result;
    var box = el("div", "walk-batch__result");
    var again = function () { findLine(line); };
    var tail = function (key) { box.appendChild(note(tx(key), "walk-form__hint--warn")); };
    if (r.status === "no_item") tail(r.photo_only ? "walk.batch.photo_none" : "walk.batch.no_item");
    else if (r.status === "unavailable" || r.status === "busy") box.appendChild(note(r.message || tx("walk.batch.unavailable"), "walk-form__hint--warn"));
    if (r.status === "no_item" || r.status === "unavailable" || r.status === "busy") {
      if (line.words.trim()) box.appendChild(W.button("walk-btn walk-btn--small", tx("walk.batch.retry"), again));
      box.appendChild(W.button("walk-btn walk-btn--small", tx("walk.sheet.class_review.other_item"), function () { pickItem(line); }));
      return box;
    }
    var item = itemOf(r.code);
    var head = el("p", "walk-batch__item");
    head.appendChild(el("strong", null, (item && item.label || r.code)));
    head.appendChild(document.createTextNode(" " + (item ? item.q : r.wording || "")));
    box.appendChild(head);
    if (r.photo_only && r.status !== "measure") seenPart(line, box);
    if (needsApproval(line) && (r.status === "found" || r.status === "need_zone")) itemConfirm(line, box);
    var where = el("p", "walk-batch__zone");
    where.setAttribute("data-batch-zone", r.zone || "");
    where.appendChild(document.createTextNode(r.zone ? tx("walk.batch.zone", { zone: zoneTitle(r.zone) }) + " — " + zoneSource(r) : zoneSource(r)));
    box.appendChild(where);
    var row = el("div", "walk-batch__row");
    row.appendChild(W.button("walk-link", tx("walk.batch.zone_change"), function () { pickZone(line); }));
    row.appendChild(W.button("walk-link", tx("walk.sheet.class_review.other_item"), function () { pickItem(line); }));
    box.appendChild(row);
    if (r.status === "measure") { tail("walk.batch.measure"); return box; }
    if (r.status === "no_facts") { tail("walk.batch.no_facts"); box.appendChild(W.button("walk-btn walk-btn--small", tx("walk.batch.retry"), again)); return box; }
    if (r.status === "need_zone") { tail("walk.batch.zone_ask"); return box; }
    classPart(line, box);
    if (levelOf(line) && repeatAsked(line)) repeatPart(line, box);
    var record = levelOf(line) && recordedFor(r.code, r.zone);
    if (record) {
      sameOrOther(line, box, record);
    } else if (levelOf(line) && duplicatedInBatch(line)) {
      tail("walk.batch.dup_batch");
    }
    return box;
  }

  function lineBadge(line) {
    if (line.saved !== null) return el("span", "walk-batch__badge is-saved", tx("walk.batch.saved"));
    if (!line.result || line.finding) return null;
    return ready(line) ? el("span", "walk-batch__badge is-ready", tx("walk.batch.ready")) : el("span", "walk-batch__badge is-doubt", tx("walk.batch.doubt"));
  }

  /** Своя слова-строка: ручная («+ ещё нарушение») пишет слова сама, строка из деления показывает свой кусок. */
  function lineWords(line, box) {
    if (!line.manual || line.result) {
      var several = line.card.lines.length > 1;
      if (several && line.words.trim() && !(line.result && line.result.photo_only)) box.appendChild(el("p", "walk-batch__said", "«" + line.words.trim() + "»"));
      return;
    }
    var area = el("textarea", "walk-area walk-area--words");
    area.rows = 2;
    area.maxLength = WORDS_MAX;
    area.placeholder = tx("walk.batch.words_hint");
    area.value = line.words;
    area.disabled = line.finding;
    area.setAttribute("data-batch-line-words", line.id);
    var go = W.button("walk-btn walk-btn--small", tx("walk.batch.line_find"), function () { findLine(line); });
    go.setAttribute("data-batch-line-find", "");
    go.disabled = true;
    area.addEventListener("input", function () { line.words = area.value; go.disabled = !area.value.trim() || b.busy; });
    box.appendChild(area);
    var voice = W.voiceBar && W.voiceBar(area, function () { line.words = area.value; go.disabled = !area.value.trim() || b.busy; });
    if (voice) box.appendChild(voice);
    go.disabled = !line.words.trim() || b.busy;
    box.appendChild(go);
  }

  function drawLine(line, index, total) {
    var li = el("li", "walk-batch__line");
    li.setAttribute("data-batch-line", line.id);
    if (line.saved !== null) li.classList.add("is-saved");
    else if (line.result && !line.finding) li.classList.add(ready(line) ? "is-ready" : "is-doubt");
    var head = el("div", "walk-batch__linehead");
    if (total > 1 || line.manual) head.appendChild(el("span", "walk-batch__linen", tx("walk.batch.line", { n: index + 1 })));
    var badge = lineBadge(line);
    if (badge) head.appendChild(badge);
    if (line.saved === null && !b.saving && (total > 1 || line.manual)) {
      var drop = W.button("walk-batch__drop", "✕", function () { dropLine(line); });
      drop.setAttribute("aria-label", tx("walk.batch.line_drop"));
      drop.setAttribute("data-batch-line-drop", "");
      head.appendChild(drop);
    }
    if (head.childNodes.length) li.appendChild(head);
    if (line.saved !== null) {
      li.appendChild(note(line.saved.n ? tx("walk.batch.saved_to", { n: line.saved.n }) : (itemOf(code(line)) || {}).q || ""));
      return li;
    }
    lineWords(line, li);
    if (line.finding) li.appendChild(note(tx("walk.batch.finding")));
    else if (line.result) li.appendChild(resultPart(line));
    if (line.error) li.appendChild(note(line.error, "walk-form__hint--warn"));
    return li;
  }

  /* ── разметка карточки ─────────────────────────────────────────────── */

  function cardClass(card) {
    var open = openLines(card);
    if (card.lines.length && !open.length) return "is-saved";
    if (card.state === "new" || card.finding) return "";
    if (card.state === "failed" || card.dirty) return "is-doubt";
    return open.every(ready) ? "is-ready" : "is-doubt";
  }

  function drawCard(card, index) {
    var li = el("li", "walk-batch__card");
    li.setAttribute("data-batch-card", card.id);
    var klass = cardClass(card);
    if (klass) li.classList.add(klass);
    var head = el("div", "walk-batch__head");
    head.appendChild(el("span", "walk-batch__n", tx("walk.batch.card", { n: index + 1 })));
    if (!hasSaved(card) && !b.saving) {
      var drop = W.button("walk-batch__drop", "✕", function () {
        card.photos.forEach(function (p) { if (p.entryId) W.offline.remove(p.entryId); });
        b.cards = b.cards.filter(function (c) { return c !== card; });
        draw();
      });
      drop.setAttribute("aria-label", tx("walk.batch.drop"));
      head.appendChild(drop);
    }
    li.appendChild(head);

    // Записанная строка уже унесла кадры к себе: список кадров и слова больше не правятся.
    if (hasSaved(card)) {
      var strip = el("div", "walk-strip");
      card.photos.forEach(function (p) {
        var cell = el("div", "walk-strip__cell is-done");
        cell.appendChild(W.photo.thumb(p));
        strip.appendChild(cell);
      });
      li.appendChild(strip);
    } else {
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
        if (card.state !== "new") card.dirty = true;
        if (was !== card.dirty || (b.bare !== undefined && b.bare !== bareCount())) draw();
      };
      area.addEventListener("input", sync);
      li.appendChild(area);
      var voice = W.voiceBar && W.voiceBar(area, sync);
      if (voice) li.appendChild(voice);
    }
    if (card.finding) li.appendChild(note(tx("walk.batch.finding")));
    if (card.dirty && !card.finding) li.appendChild(W.button("walk-btn walk-btn--small", tx("walk.batch.retry"), function () { find([card]); }));
    if (card.state === "failed" && !card.finding && !card.dirty) {
      li.appendChild(note(card.error, "walk-form__hint--warn"));
      li.appendChild(W.button("walk-btn walk-btn--small", tx("walk.batch.retry"), function () { find([card]); }));
    }
    if (card.splitFailed && !card.finding) li.appendChild(note(tx("walk.batch.split_failed"), "walk-form__hint--warn"));
    if (card.lines.length && !card.finding) {
      var list = el("ul", "walk-batch__lines");
      card.lines.forEach(function (line, i) { list.appendChild(drawLine(line, i, card.lines.length)); });
      li.appendChild(list);
    }
    if (card.state !== "new" && !card.finding && !b.saving) {
      var more = W.button("walk-btn walk-btn--small walk-batch__more", tx("walk.batch.add_line"), function () { addLine(card); });
      more.setAttribute("data-batch-add-line", card.id);
      li.appendChild(more);
    }
    return li;
  }

  function pickInput() {
    if (b.cards.length >= MAX_CARDS) {
      var full = note(tx("walk.batch.full", { n: MAX_CARDS }));
      full.setAttribute("data-batch-full", "");
      return full;
    }
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
    var lines = allLines().filter(function (l) { return l.saved === null; });
    var pending = unsearched();
    var good = lines.filter(ready);
    var left = lines.length - good.length;
    if (b.error) foot.appendChild(note(b.error, "walk-form__hint--warn"));
    var searched = b.cards.some(function (c) { return c.state !== "new"; });
    if (searched && left > 0 && good.length) foot.appendChild(note(tx("walk.batch.waiting_n", { n: left })));
    if (pending.length) {
      var bare = bareCount();
      b.bare = bare;
      if (bare) {
        var warn = note(tx("walk.batch.photo_warn", { n: bare }), "walk-form__hint--warn");
        warn.setAttribute("data-batch-photo-warn", "");
        foot.appendChild(warn);
      }
      var blocked = pending.some(function (c) { return photosPending(c); });
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
    var focusAttr = active && active.getAttribute && ["data-batch-words", "data-batch-seen", "data-batch-line-words"].filter(function (a) { return active.getAttribute(a); })[0];
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
      if (hasSaved(card)) return;
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
