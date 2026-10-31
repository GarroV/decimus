/* Мини-апп обхода: форма записи (D312) — нарушение, рекомендация, замер, правка.
 * Как устроена и почему — docs/13-walk-mini-app.md, раздел о форме записи.
 *
 * Нарушение (D330): кадр и пара слов → «Найти пункт» → система (та же, что у
 * бота, `/tg/walk/suggest`) предлагает карточки, верхняя выбрана → человек
 * проверяет и жмёт «Сохранить». Ручной поиск — запасной путь из меню. Вид записи
 * (и зона — у правки, рекомендации, замера) — строкой над формой, выбор — меню
 * снизу (`walk-menu.js`).
 *
 * Зона нарушения (D445) не берётся с экрана: после того как пункт найден, её
 * выводит сервер (`resolution` у карточки) по пункту, словам и подсказке с
 * экрана; не вывелась — форма спрашивает пилюлями «Где?» и не даёт сохранить.
 * Результат — одна строка «пункт · зона», зона в ней — пилюля с меню.
 * Одним кадром бывает видно два нарушения (сломанный дозатор и в нём нет мыла):
 * у невыбранной карточки есть «Тоже записать» (D593) — отмеченные пункты
 * сохраняются отдельными записями с подтверждёнными кадрами, следом за
 * основной; дополнительная запись требует своей явно выведенной зоны.
 * Рекомендация (D201, класс R) и общая заметка (D314, код NOTE) — без вычета,
 * текст обязателен. Замер (D0) — со стоянки «Печь и холодильники» (D315).
 *
 * Показание термометра (#836): модель читает цифры с дисплея и путается (6 °C
 * как 26 °C), поэтому при показании у карточки или записи в форме есть поле
 * «Температура, °C». Изменённое число «Сохранить» не пишет, а пересчитывает
 * предложение (тот же поиск с `reading_c`) — новое предложение ждёт «Сохранить»
 * как любое другое.
 *
 * Правила методики форма подсказывает, а не решает: без фото не сохранить
 * (D078), классы — только допустимые для пункта, пункт, уже записанный в этой
 * зоне, — новые фото к той записи, повтор ставит человек (D191); окончательно
 * проверяет движок, и его отказ показывается его словами.
 *
 * Поля ввода не перерисовываются на каждый знак — иначе на телефоне слетает
 * клавиатура. Перерисовываются только секции, которые от выбора зависят.
 */
(function () {
  "use strict";

  var W = window.DecimusWalk;
  var tx = W.tx;
  var el = W.el;
  var f = null; // открытая форма
  var node = null;
  var parts = {};
  var seq = 0;
  var returnScrollY = 0;

  /* ── данные формы ─────────────────────────────────────────────────── */

  function draftKey() { return f.draftKey; }

  function loadDraft() {
    var data = W.state.data;
    var draft = W.local.get(draftKey());
    if (draft && data.run_id && draft.run_id === data.run_id) return draft;
    var legacy = W.local.get(data.legacy_key + "_draft");
    if (legacy && data.run_id && legacy.run_id === data.run_id) {
      W.local.set(draftKey(), legacy);
      return legacy;
    }
    return null; // Unknown legacy drafts stay untouched for recovery.
  }

  function recoveryPanel(body) {
    var data = W.state.data;
    var oldKey = data.legacy_key + "_draft";
    var old = W.local.get(oldKey);
    var current = f;
    var panel = el("details", "walk-form__note walk-form__note--info");
    var summary = el("summary", "", tx("walk.draft.recovery"));
    panel.appendChild(summary);
    function show(entries) {
      if (!f || f !== current || (!old && !entries.length)) return;
      panel.appendChild(el("p", "", tx("walk.draft.unknown")));
      if (old) panel.appendChild(el("pre", "", [old.code, old.words, old.text, old.comment].filter(Boolean).join("\n")));
      ((old && old.photos) || []).forEach(function (ref) {
        panel.appendChild(W.photo.thumb({ref: ref, own: true}));
      });
      entries.forEach(function (entry) {
        var url = URL.createObjectURL(entry.blob);
        var img = el("img", "walk-thumb__img");
        img.alt = tx("walk.draft.recovery"); img.src = url;
        img.onload = function () { URL.revokeObjectURL(url); };
        panel.appendChild(img);
      });
      var button = W.button("walk-btn", tx("walk.draft.copy"), function () {
        if (!window.confirm(tx("walk.draft.confirm"))) return;
        button.disabled = true;
        var copied = Object.assign({}, old || {mode: current.mode}, {run_id: current.run_id});
        W.local.set(current.draftKey, copied);
        // Copy bytes, keeping all original keys and frames as a recovery source.
        Promise.all(entries.map(function (entry) {
          return W.offline.put(current.draftKey, entry.mode, entry.blob, current.run_id);
        })).then(function () {
          if (f !== current) return;
          open({mode: copied.mode || current.mode});
        }, function () { button.disabled = false; W.toast(tx("walk.offline.nostore"), "warn"); });
      });
      panel.appendChild(button);
      body.insertBefore(panel, body.firstChild);
    }
    W.offline.recovery(oldKey).then(show);
  }

  function zoneOf(code) {
    return W.state.data.zones.filter(function (z) { return z.code === code; })[0] || null;
  }

  /** Общая заметка: рекомендация не про пункт — уходит в конец отчёта. */
  var NOTE_CODE = "NOTE";

  function noteItem() {
    return { code: NOTE_CODE, q: tx("walk.note.item"), process: "", zones: [], levels: [], measure: false, note: true };
  }

  function item(code) {
    if (code === NOTE_CODE) return noteItem();
    return W.state.data.items.filter(function (i) { return i.code === code; })[0] || null;
  }

  function isMeasure() { return f.mode === "measure"; }

  /* ── показание термометра (#836) ──────────────────────────────────── */

  var READING_MIN = -60;
  var READING_MAX = 500;

  /** Число из поля: «6», «-18», «4,5», «6 °C»; не число или вне термометра — null. */
  function parseReading(raw) {
    var m = /^\s*([+\-\u2212]?\d{1,3}(?:[.,]\d{1,2})?)\s*(?:°\s*[CcСс]?)?\s*$/.exec(String(raw == null ? "" : raw));
    if (!m) return null;
    var v = parseFloat(m[1].replace(",", ".").replace("\u2212", "-"));
    return v >= READING_MIN && v <= READING_MAX ? v : null;
  }

  /** У формы есть показание: поле показано, пока оно не null (пустая строка — поле есть, число стёрто). */
  function hasReading() { return f.reading !== null && f.reading !== undefined; }

  /** Число в поле отличается от того, по которому предложение уже посчитано. */
  function readingChanged() {
    if (!hasReading()) return false;
    var v = f.reading.trim() === "" ? null : parseReading(f.reading);
    return v !== f.readingBase;
  }

  /** Поле непустое, но не число: сохранять и пересчитывать нельзя. */
  function readingInvalid() { return hasReading() && f.reading.trim() !== "" && parseReading(f.reading) === null; }

  function hasNoViolation() { return f.noViolation !== null && f.noViolation !== undefined; }

  function setReading(value, source, confirmed) {
    f.reading = value === null || value === undefined ? null : String(value);
    f.readingBase = value === null || value === undefined ? null : value;
    f.readingSource = source || "human";
    f.readingConfirmed = confirmed === true || (!!f.n && confirmed === undefined);
    f.noViolation = null;
  }

  /** Рекомендация без нарушения (D201): у пункта, без класса и вычета. */
  function isAdvice() { return f.mode === "advice"; }

  var ADVICE_LEVEL = "R";

  /** Нарушение по этому пункту в этой зоне — рекомендацию можно дописать в него. */
  function violationHere() {
    var zone = zoneOf(f.zone);
    if (!zone || !f.code) return null;
    return zone.recorded.filter(function (r) {
      return r.code === f.code && r.level !== "D0" && r.level !== ADVICE_LEVEL;
    })[0] || null;
  }

  function previousHere(code) {
    var zone = zoneOf(f.zone);
    if (!zone) return null;
    return zone.previous.filter(function (p) { return p.code === code; })[0] || null;
  }

  function taken() {
    if (isMeasure() || isAdvice() || !f.code || !f.zone || f.n) return null;
    return violationHere();
  }

  function repeatOffered() {
    return !isMeasure() && !isAdvice() && !taken() && !!f.code && (f.level === "D1" || f.level === "D2") && !!previousHere(f.code);
  }

  function unusual() {
    var it = item(f.code);
    return !!(it && f.zone && it.zones.length && it.zones.indexOf(f.zone) === -1);
  }

  function choices(query) {
    var q = (query || "").trim().toLowerCase();
    var list = W.state.data.items.filter(function (i) {
      if (i.measure !== isMeasure()) return false;
      if (q) return (i.q + " " + i.code + " " + i.process).toLowerCase().indexOf(q) !== -1;
      return true;
    });
    var hint = f.zone || f.hint;
    list.sort(function (a, b) {
      var aHere = !hint || !a.zones.length || a.zones.indexOf(hint) !== -1;
      var bHere = !hint || !b.zones.length || b.zones.indexOf(hint) !== -1;
      return Number(bHere) - Number(aHere);
    });
    var before = list.filter(function (i) { return previousHere(i.code); });
    return before.concat(list.filter(function (i) { return !previousHere(i.code); }));
  }

  function uploading() { return f.photos.some(function (p) { return p.state === "uploading"; }); }

  /** Кадры, которым не хватило связи: ждут на телефоне (D442). */
  function waitingPhotos() { return f.photos.filter(function (p) { return p.state === "waiting"; }); }

  function readyPhotos() { return f.photos.filter(function (p) { return p.state === "done"; }); }

  /** Новое нарушение без выбранного пункта: пункт ищет система (D330). */
  function recognizing() { return !f.n && f.mode === "violation"; }

  /** Что мешает спросить систему: без кадра нарушение не разбирается (D078). */
  function findBlocker() {
    if (!readyPhotos().length) return missingPhoto();
    if (uploading()) return "walk.sheet.need_upload";
    return null;
  }

  /** Готовых кадров нет: загружаются, ждут связи или не снято вовсе. */
  function missingPhoto() {
    if (uploading()) return "walk.sheet.need_upload";
    return waitingPhotos().length ? "walk.sheet.need_online" : "walk.sheet.need_photo";
  }

  function blocker() {
    // Рекомендации кадр не обязателен: «крышка открывается туго» не снять.
    if (!isAdvice() && !readyPhotos().length) return missingPhoto();
    if (uploading()) return "walk.sheet.need_upload";
    // Кадр, ждущий связи, нельзя бросить за порогом записи: она ушла бы без него.
    if (waitingPhotos().length) return "walk.sheet.need_online";
    if (f.photos.some(function (p) { return p.state === "failed" && !p.entryId; })) return "walk.offline.nostore";
    // Число после «нарушения нет» поправлено: «Пересчитать» доступно без пункта.
    if (f.noViolation !== null && readingChanged() && !readingInvalid()) return null;
    if (!f.zone) return recognizing() && f.code ? "walk.sheet.need_where" : "walk.sheet.need_zone";
    if (!f.code) return "walk.sheet.need_item";
    if (readingInvalid()) return "walk.err.reading";
    if (assignmentEnabled() && (!assignmentReady(primaryPhotoCandidate()) ||
        extras().some(function (c) { return !assignmentReady(c); }))) return "walk.sheet.photo_assignment.need";
    if (isAdvice()) return f.text.trim() ? null : "walk.sheet.need_advice";
    if (!f.n && !taken() && ["D1", "D2", "D3"].indexOf(f.level) !== -1 && !f.text.trim()) return "walk.sheet.need_factual_text";
    if (extras().some(function (cand) {return ["D1", "D2", "D3"].indexOf(extraLevel(cand)) !== -1 && !extraText(cand).trim();})) return "walk.sheet.need_factual_text";
    var classWhy = classBlocker();
    if (classWhy) return classWhy;
    if (!taken() && !f.level) return "walk.sheet.need_level";
    return null;
  }

  function dirty() {
    // Пункт, подставленный чек-листом или «Не исправлено», — не ввод человека:
    // «Назад» без единого действия не спрашивает «выбросить?».
    if (!f.n) return !!(f.photos.length || f.text || f.comment || f.words) || f.code !== f.preset;
    var o = f.original;
    return f.text !== o.text || f.comment !== o.comment || f.level !== o.level ||
      f.zone !== o.zone || f.code !== o.code || f.repeat !== o.repeat || readingChanged() ||
      f.photos.some(function (p) { return p.fresh; }) || f.removed.length > 0;
  }

  function saveDraft() {
    if (f.n) { if (W.editDraft) W.editDraft.save(f); return; }
    W.local.set(draftKey(), Object.assign({}, W.local.get(draftKey()) || {}, {
      run_id: f.run_id, mode: f.mode, zone: f.zone, code: f.code,
      level: f.level || f.legacyLevel || null, text: f.text,
      comment: f.comment, repeat: f.repeat, words: f.words, reading: f.reading,
      reading_source: f.readingSource || "model", reading_confirmed: !!f.readingConfirmed,
      class_facts: classFactDrafts(),
      photos: readyPhotos().map(function (p) { return p.ref; }),
      reconcile: !!f.reconcile, submitted_ops: f.submitted_ops || [],
    }));
  }

  function changed() {
    syncClassSelections();
    saveDraft();
    if (W.tg && W.supports("6.2")) {
      if (dirty()) W.tg.enableClosingConfirmation(); else W.tg.disableClosingConfirmation();
    }
  }

  /* ── кадры ────────────────────────────────────────────────────────── */

  function addFiles(files) {
    // Кадр новой записи при обрыве связи переживёт закрытие формы: он привязан к черновику.
    var key = !f.n || hasEditDraft() ? draftKey() : null;
    var mode = f.mode;
    files.forEach(function (file) {
      var p = { id: ++seq, state: "uploading", fresh: true, own: true, url: URL.createObjectURL(file), draftKey: key, run_id: f.run_id, mode: mode };
      f.photos.push(p);
      send(p, file);
    });
    redraw("photos", "item", "footer");
  }

  function send(p, file) {
    p.state = "uploading";
    if (p.draftKey) {
      var stored = p.entryId && W.offline.retry ? W.offline.retry(p.entryId, p.draftKey, p.run_id) :
        (p.blob ? Promise.resolve(p.blob) : W.photo.compress(file)).then(function (blob) {
          p.blob = blob;
          if (!W.offline.available()) throw new Error("storage");
          return W.offline.put(p.draftKey, p.mode, blob, p.run_id).then(function (entry) {
            p.entryId = entry.id; p.receiptIds = [entry.id];
          });
        });
      stored.then(function () {
        p.state = "waiting";
        if (f && f.photos.indexOf(p) !== -1) redraw("photos", "item", "footer");
        W.offline.kick(); W.offline.watch();
      }, function () {
        p.state = "failed"; p.file = file;
        W.toast(tx("walk.offline.nostore"), "warn");
        if (f && f.photos.indexOf(p) !== -1) redraw("photos", "item", "footer");
      });
      return;
    }
    var blob = p.blob ? Promise.resolve(p.blob) : W.photo.compress(file);
    blob.then(function (b) {
      p.blob = b;
      if (navigator.onLine === false) throw W.photo.offline();
      return W.photo.upload(b, p.run_id);
    }).then(function (ref) {
      if (!f || f.photos.indexOf(p) === -1) return;
      p.ref = ref;
      p.state = "done";
      W.photo.remember(ref, p.url);
      changed();
      redraw("photos", "item", "footer");
    }, function (err) {
      if (err && (err.retryable || err.code === "run_changed" || err.status === 409) && p.blob) { park(p, file); return; }
      if (!f || f.photos.indexOf(p) === -1) return;
      p.state = "failed";
      p.error = err && err.message;
      p.file = file;
      redraw("photos", "item", "footer");
    });
  }

  /** Не дошло из-за сети: кадр ждёт связи. Новой записи — в хранилище телефона, иначе в памяти формы. */
  function park(p, file) {
    var shown = function () { return !!f && f.photos.indexOf(p) !== -1; };
    var failed = function (reason) {
      W.toast(tx(reason === "full" ? "walk.offline.full" : "walk.offline.nostore"), "warn");
      if (!shown()) return;
      p.state = "failed";
      p.file = file;
      redraw("photos", "item", "footer");
    };
    if (!p.draftKey || p.entryId) {
      // Правка записи — кадр ждёт в памяти формы; уже лежащий в хранилище — только перерисовать.
      if (shown()) {
        p.state = "waiting";
        p.file = file;
        redraw("photos", "item", "footer");
      }
      W.offline.watch();
      return;
    }
    W.offline.put(p.draftKey, p.mode, p.blob, p.run_id).then(function (entry) {
      p.entryId = entry.id;
      if (shown()) {
        p.state = "waiting";
        redraw("photos", "item", "footer");
      }
      W.toast(tx("walk.offline.parked"), "warn");
      W.offline.watch();
    }, function (err) { failed(err && err.reason); });
  }

  /** Фон отправил кадр из хранилища. Форма на том же черновике открыта — кадр становится готовым в ней. */
  function adopt(entry, ref) {
    if (!f || (f.n && !hasEditDraft()) || f.run_id !== entry.run_id || draftKey() !== entry.key) return false;
    if (f.gone.indexOf(entry.id) !== -1) return true;
    var exact = f.photos.filter(function (x) { return x.entryId === entry.id; })[0];
    var existing = f.photos.filter(function (x) { return x.ref === ref; })[0];
    if (exact && existing && exact !== existing) {
      f.photos = f.photos.filter(function (x) { return x !== exact; });
      if (exact.url) URL.revokeObjectURL(exact.url);
    }
    var p = existing || exact;
    if (!p) {
      p = { id: ++seq, fresh: true, own: true, draftKey: entry.key, run_id: entry.run_id, mode: entry.mode, url: URL.createObjectURL(entry.blob) };
      f.photos.push(p);
    }
    p.ref = ref;
    p.state = "done";
    p.entryId = entry.id;
    p.receiptIds = (p.receiptIds || []).concat(exact && exact.receiptIds || [], [entry.id]).filter(function (id, at, all) { return all.indexOf(id) === at; });
    if (!p.url) p.url = URL.createObjectURL(entry.blob);
    W.photo.remember(ref, p.url);
    changed();
    redraw("photos", "item", "footer");
    return true;
  }

  function uploadFailed(entry) {
    if (!f || (f.n && !hasEditDraft()) || f.run_id !== entry.run_id || draftKey() !== entry.key) return false;
    var p = f.photos.filter(function (p) { return p.entryId === entry.id; })[0];
    if (p) { p.state = "failed"; redraw("photos", "item", "footer"); }
    return true;
  }

  /** Раз в попытку: кадры, ждущие в памяти формы (правка записи), пробуем снова. */
  function retryInMemory() {
    if (!f) return 0;
    var list = waitingPhotos().filter(function (p) { return !p.entryId && p.file; });
    list.forEach(function (p) { send(p, p.file); });
    return list.length;
  }

  /** Форма открылась: кадры этого черновика, дожидавшиеся связи, возвращаются в неё. */
  function restoreWaiting() {
    if ((f.n && !hasEditDraft()) || !W.offline.available()) return;
    var mine = f;
    W.offline.list(draftKey()).then(function (entries) {
      if (f !== mine) return;
      var added = false;
      entries.forEach(function (e) {
        if (e.mode !== f.mode || f.gone.indexOf(e.id) !== -1) return;
        if (e.uploaded_ref) { adopt(e, e.uploaded_ref); return; }
        if (f.photos.some(function (x) { return x.entryId === e.id; })) return;
        f.photos.push({
          id: ++seq, state: e.upload_error ? "failed" : "waiting", fresh: true, own: true, entryId: e.id, receiptIds: [e.id], draftKey: e.key, run_id: e.run_id,
          mode: e.mode, blob: e.blob, url: URL.createObjectURL(e.blob),
        });
        added = true;
      });
      if (!added) return;
      changed();
      redraw("photos", "item", "footer");
      W.offline.kick();
    });
  }

  function removePhoto(p) {
    var left = f.photos.filter(function (x) { return x !== p; });
    if (f.n && !isAdvice() && !left.some(function (x) { return x.state === "done"; })) {
      W.toast(tx("walk.photo.last"), "warn");
      return;
    }
    if (!p.fresh && p.ref) f.removed.push(p.ref);
    (p.receiptIds || (p.entryId ? [p.entryId] : [])).forEach(function (id) { f.gone.push(id); W.offline.remove(id); });
    f.photos = left;
    changed();
    redraw("photos", "item", "footer");
  }

  /* ── секции ───────────────────────────────────────────────────────── */

  function section(title, hint) {
    var box = el("section", "walk-form__part");
    if (title) box.appendChild(el("h3", "walk-form__label", title));
    if (hint) box.appendChild(el("p", "walk-form__hint", hint));
    return box;
  }

  // Замер в переключателе не стоит: он вносится с остановки «Оборудование».
  var KINDS = [["violation", "walk.kind.violation"], ["advice", "walk.kind.advice"]];

  /** Смена вида записи: пункт остаётся, если он годится новому виду. */
  function setMode(mode) {
    if (mode === f.mode) return;
    f.mode = mode;
    var it = item(f.code);
    if (it && (it.measure !== (mode === "measure") || (it.note && mode !== "advice"))) f.code = null;
    f.level = mode === "advice" ? ADVICE_LEVEL : mode === "measure" ? "D0" : null;
    if (mode === "violation" && f.code) {
      var chosen = item(f.code);
      if (chosen && chosen.levels.length === 1) f.level = chosen.levels[0];
    }
    f.repeat = false;
    f.picked = null;
    f.also = [];
    // Рекомендации и замеру зону показывает пилюля над формой — подсказка с
    // экрана ложится в неё видимо, а не молча.
    if (mode !== "violation" && !f.zone && f.hint) f.zone = f.hint;
    W.haptic();
    changed();
    node.querySelector(".walk-sheet__title").textContent = titleText();
    redraw.apply(null, ORDER.concat(["footer"]));
  }

  function titleText() {
    if (f.n) return isAdvice() ? tx("walk.sheet.edit_advice", { n: f.n }) : tx("walk.sheet.edit", { n: f.n });
    if (isMeasure()) return tx("walk.sheet.new_measure");
    return isAdvice() ? tx("walk.sheet.new_advice") : tx("walk.sheet.new");
  }

  /* ── выбор из меню ─────────────────────────────────────────────────── */

  function realZones() { return W.state.data.zones.filter(function (z) { return !z.equipment; }); }

  /** Зоны пункта в порядке методики; пункт «во всех зонах» — все. */
  function itemZones(code) {
    var it = item(code);
    var all = realZones();
    if (!it || !it.zones.length || it.zones.indexOf("*") !== -1) return all;
    return all.filter(function (z) { return it.zones.indexOf(z.code) !== -1; });
  }

  function setZone(code, source) {
    f.zone = code;
    f.zoneSource = source;
    W.haptic();
    changed();
    redraw.apply(null, ORDER.concat(["footer"]));
    if (recognizing() && f.code) requestClass(primaryClassCandidate());
  }

  function fullZoneMenu() {
    W.menu.open({
      title: tx("walk.sheet.zone"),
      options: realZones().map(function (z) { return { label: z.title, value: z.code, on: z.code === f.zone }; }),
      onPick: function (code) { setZone(code, "pick"); },
    });
  }

  /**
   * Меню зоны: сначала зоны пункта, дальше «Другая зона…» — выбор вне списка
   * пункта остаётся возможным и помечается для перепроверки (`unusual`).
   */
  function zoneMenu() {
    var own = f.code && !isAdvice() && !isMeasure() ? itemZones(f.code) : [];
    if (!own.length || own.length === realZones().length) { fullZoneMenu(); return; }
    var options = own.map(function (z) { return { label: z.title, value: z.code, on: z.code === f.zone }; });
    var other = !!f.zone && !own.some(function (z) { return z.code === f.zone; });
    options.push({ label: tx("walk.sheet.zone_other"), value: "__other", on: other, lead: true });
    W.menu.open({
      title: tx("walk.sheet.zone"),
      options: options,
      onPick: function (code) { if (code === "__other") fullZoneMenu(); else setZone(code, "pick"); },
    });
  }

  function kindMenu() {
    W.menu.open({
      title: tx("walk.sheet.kind"),
      options: KINDS.map(function (pair) {
        return { label: tx(pair[1]), hint: tx(pair[1] + "_hint"), value: pair[0], on: f.mode === pair[0] };
      }),
      onPick: setMode,
    });
  }

  /** Пункт вручную — запасной путь, когда система не нашла нужного. */
  function itemMenu() {
    var lead = isAdvice() ? [{ label: tx("walk.note.item"), hint: tx("walk.note.hint"), value: NOTE_CODE, lead: true }] : [];
    W.menu.search({
      title: isMeasure() ? tx("walk.sheet.item_measure") : isAdvice() ? tx("walk.sheet.item_advice") : tx("walk.sheet.item"),
      placeholder: isMeasure() ? tx("walk.sheet.search_measure") : tx("walk.sheet.search"),
      lead: lead,
      semanticTags: isMeasure() || isAdvice() ? [] : (W.state.data.item_search_tags || []).map(function (tag) {
        return {id:tag.id, label:tx("walk.sheet.search_tag." + tag.id), codes:tag.codes};
      }),
      tags: choices("").map(function (i) { return i.process; }).filter(function (p, at, all) { return p && all.indexOf(p) === at; }),
      list: function (q, filters) {
        filters = filters || {};
        var selectedTag = (W.state.data.item_search_tags || []).filter(function (tag) {return tag.id === filters.semantic;})[0];
        return choices(q).filter(function (i) {
          return (!filters.process || i.process === filters.process) &&
            (!selectedTag || selectedTag.codes.indexOf(i.code) !== -1);
        }).map(function (i) {
          return { code: i.label, kind: isAdvice() ? "advice" : i.measure ? "info" : "violation", label: i.q, value: i.code, on: i.code === f.code, badge: previousHere(i.code) ? tx("walk.sheet.was_here") : null };
        });
      },
      onPick: function (code) { pick(code, null); },
    });
  }

  /**
   * Зона нового нарушения по найденному пункту (D445). Предложение системы
   * несёт готовый вывод сервера; ручной выбор повторяет его без слов: одна зона
   * пункта — она, иначе зона с экрана, если она у пункта есть, иначе спросить.
   */
  function applyResolution(i, cand) {
    var r = cand && cand.resolution;
    if (!r) {
      var own = itemZones(i.code);
      var hint = f.hint && own.some(function (z) { return z.code === f.hint; }) ? f.hint : null;
      r = own.length === 1 ? { zone: own[0].code, source: "single" } : hint ? { zone: hint, source: "hint" } : { zone: null, source: "ask" };
    }
    f.zone = r.zone && zoneOf(r.zone) && !zoneOf(r.zone).equipment ? r.zone : null;
    f.zoneSource = f.zone ? r.source : "ask";
  }

  /**
   * Выбрать пункт — предложенный системой (`cand`) или вручную.
   * Класс и формулировку предложения форма берёт как черновик: поправить их
   * можно ниже, а записывается всё только по «Сохранить».
   */
  function pick(code, cand) {
    var i = item(code);
    if (!i) return;
    if (recognizing() && f.code) {
      f.savedClassFacts = classFactDrafts();
      var old = classState(primaryClassCandidate());
      old.reading = f.reading == null ? "" : f.reading;
      old.readingSource = f.readingSource || "human";
      old.readingConfirmed = !!f.readingConfirmed;
    }
    // Явный выбор зоны сохраняется у кандидата, когда человек переходит к
    // другому варианту. Исходная model zone (cand.zone) остаётся нетронутой.
    if (f.picked && f.zone && f.zoneSource === "pick") {
      var previous = f.picked.resolution || {};
      previous.zone = f.zone;
      previous.source = "pick";
      f.picked.resolution = previous;
    }
    f.code = code;
    f.picked = cand ? cand : null;
    if (recognizing()) applyResolution(i, cand);
    // Основной стала одна пара «пункт + зона»; другие зоны остаются в «тоже».
    f.also = f.also.filter(function (c) { return !isPrimary(c); });
    if (recognizing() && !i.measure && !i.note) {
      var review = classState(primaryClassCandidate());
      review.key = null;
      review.manualMode = false;
      f.level = null;
      f.legacyLevel = null;
    } else {
      if (i.measure) f.level = "D0";
      else if (isAdvice() || i.note) f.level = ADVICE_LEVEL;
      else if (cand && i.levels.indexOf(cand.level) !== -1) f.level = cand.level;
      else if (i.levels.length === 1) f.level = i.levels[0];
      else if (i.levels.indexOf(f.level) === -1) f.level = null;
      var before = previousHere(code);
      if (before && !isAdvice() && !f.level && i.levels.indexOf(before.level) !== -1) f.level = before.level;
    }
    if (cand && cand.wording && (!f.text.trim() || f.textAuto)) { f.text = cand.wording; f.textAuto = true; }
    if (recognizing()) {
      var ownReading = classState(primaryClassCandidate());
      setReading(ownReading.reading === "" ? null : ownReading.reading,
        ownReading.readingSource, ownReading.readingConfirmed);
    } else if (cand && cand.reading_c != null) setReading(cand.reading_c);
    W.haptic();
    changed();
    redraw.apply(null, ORDER.concat(["footer"]));
    if (recognizing()) requestClass(primaryClassCandidate());
  }

  /* ── система ищет пункт (D330) ─────────────────────────────────────── */

  function find(reading) {
    if (findBlocker() || f.finding) return;
    if (recognizing() && f.code) f.savedClassFacts = classFactDrafts();
    var form = f;
    var runId = f.run_id;
    f.finding = true;
    f.findError = null;
    // Простой поиск (без исправленного числа) начинает разговор заново.
    if (typeof reading !== "number") f.noViolation = null;
    redraw("item", "reading", "footer");
    var asked = { words: (f.n ? (f.words || f.text) : f.words).trim(), photos: readyPhotos().map(function (p) { return p.ref; }) };
    var body = { zone_hint: f.zone || f.hint || null, words: asked.words, photos: asked.photos };
    // Исправленная температура (#836): тот же поиск с утверждением «реально N °C».
    var fixed = typeof reading === "number" ? reading : null;
    if (fixed !== null) body.reading_c = fixed;
    // Номер поиска: выбор предварительной карточки увеличивает его, и ответ модели на
    // этот поиск уже не применяется — выбор человека он не перебивает.
    f.findId = (f.findId || 0) + 1;
    var mine = f.findId;
    f.preview = null;
    f.hintCodes = null;
    f.pending = asked;
    if (fixed === null && asked.words) preview(mine, asked, body.zone_hint);
    W.post(W.urls.suggest, body).then(function (res) {
      if (f !== form || W.state.data.run_id !== runId || f.findId !== mine) return;
      if (!res.ok) throw new Error((res.body && res.body.message) || tx("walk.error"));
      f.finding = false;
      f.preview = null;
      f.found = (res.body && res.body.candidates) || [];
      f.also = [];
      f.question = (res.body && res.body.question) || "";
      f.answers = (res.body && res.body.answers) || [];
      f.answered = null;
      f.via = (res.body && res.body.via) || "model";
      f.asked = JSON.stringify(asked);
      if (recognizing()) {
        f.code = null; f.zone = null; f.level = null; f.picked = null;
        f.legacyLevel = null;
        f.question = ""; f.answers = [];
        redraw.apply(null, ORDER.concat(["footer"]));
      } else if (f.found.length) {
        if (fixed !== null) {
          // Предложение посчитано заново: формулировка и класс — новые, число — аудитора.
          f.textAuto = true;
          f.text = f.found[0].wording || f.text;
          setReading(fixed);
        }
        pick(f.found[0].code, f.found[0]);
      } else if (fixed !== null) {
        // При этой температуре нарушения нет — запись не создаётся.
        setReading(fixed);
        f.noViolation = fixed;
        f.code = null; f.level = null; f.picked = null; f.zone = null;
        redraw.apply(null, ORDER.concat(["footer"]));
      } else { redraw("item", "footer"); }
    }).catch(function (err) {
      if (f !== form || W.state.data.run_id !== runId || f.findId !== mine) return;
      f.finding = false;
      f.findError = err && err.message && err.message !== "Failed to fetch" ? err.message : tx("walk.err.network");
      redraw("item", "reading", "footer");
    });
  }

  /**
   * Мгновенная подсказка (#1267): 2–3 пункта по словарю и выученным фразам, пока модель
   * думает. Приходит за доли секунды и живёт, пока идёт поиск; пусто и сбой — молча,
   * экран ждёт модель как раньше.
   */
  function preview(mine, asked, zone) {
    var form = f;
    var runId = f.run_id;
    W.post(W.urls.hint, { zone_hint: zone, words: asked.words, frames: asked.photos.length }).then(function (res) {
      if (f !== form || W.state.data.run_id !== runId || !f.finding || f.findId !== mine || !res.ok) return;
      var cards = (res.body && res.body.candidates) || [];
      if (!cards.length) return;
      f.preview = cards;
      // Что показали — уходит с записью: по нему считается, угадала ли подсказка (#1267).
      f.hintCodes = cards.map(function (c) { return c.code; });
      redraw("item");
    }).catch(function () { /* подсказка — добавка к поиску, а не его часть */ });
  }

  /**
   * Аудитор нажал предварительную карточку, не дожидаясь модели. Дальше — обычный
   * выбор пункта: зона выводится теми же правилами, фиксирует человек «Сохранить».
   */
  function pickPreview(cand) {
    f.findId += 1;
    f.finding = false;
    f.found = f.preview || [cand];
    f.preview = null;
    f.also = [];
    f.question = "";
    f.answers = [];
    f.answered = null;
    f.via = "hint";
    f.asked = JSON.stringify(f.pending);
    pick(cand.code, cand);
  }

  /** Слова или кадры поменялись после поиска — предложения могли устареть. */
  function stale() {
    if (!f.found) return false;
    return f.asked !== JSON.stringify({ words: f.words.trim(), photos: readyPhotos().map(function (p) { return p.ref; }) });
  }

  function proposal(cand, onPick) {
    var i = item(cand.code) || { q: cand.code };
    var on = f.picked ? f.picked === cand : isPrimary(cand);
    var top = el("span", "walk-found__top");
    var kind = cand.level === ADVICE_LEVEL ? "advice" : cand.level === "D0" || i.measure ? "info" : /^D[1-3]$/.test(cand.level || "") ? "violation" : null;
    top.appendChild(el("span", "walk-option__code" + (kind ? " walk-item-code--" + kind : ""), i.label || cand.code));
    if (kind) top.appendChild(el("span", "walk-item-kind walk-item-kind--" + kind, tx("walk.item.kind." + kind)));
    if (!recognizing() && cand.level && cand.level !== ADVICE_LEVEL) top.appendChild(W.level(cand.level));
    if (on) {
      // Выбранная карточка — результат «пункт · зона» (D445): зона — пилюля с
      // меню. Не вывелась — пилюли нет, под карточкой строка «Где?».
      var card = el("div", "walk-found__card is-on");
      card.appendChild(top);
      var line = W.hinted(el("span", "walk-found__q walk-found__line"), "itemzone");
      line.appendChild(el("span", "walk-found__item", i.q));
      var z = zoneOf(f.zone);
      if (z) {
        // Точка остаётся на конце названия: на узком экране пилюля уходит на
        // вторую строку, а точка не оказывается в начале неё.
        line.firstChild.textContent = i.q + " ·";
        var pill = W.button("walk-ctx__pill walk-ctx__pill--zone", z.title, zoneMenu);
        pill.setAttribute("aria-label", tx("walk.sheet.zone") + ": " + z.title);
        line.appendChild(pill);
      }
      card.appendChild(line);
      var assigned = photoAssignmentControl(f.picked || primaryPhotoCandidate());
      if (assigned) card.appendChild(assigned);
      return card;
    }
    var b = W.button("walk-found__card", null, function () { if (onPick) onPick(cand); else pick(cand.code, cand); });
    b.setAttribute("aria-pressed", "false");
    b.appendChild(top);
    var resolved = zoneOf(extraZone(cand));
    b.appendChild(el("span", "walk-found__q", i.q + " · " + (resolved ? resolved.title : tx("walk.sheet.where"))));
    if (!recognizing() || !f.code || !item(cand.code)) return b;
    // «Тоже записать» (D593) — рядом с карточкой, а не в ней: кнопка в кнопке недопустима.
    var row = el("div", "walk-found__row");
    var also = isAlso(cand);
    var t = W.button("walk-found__also" + (also ? " is-on" : ""), tx(also ? "walk.sheet.also_on" : "walk.sheet.also"), function () { toggleAlso(cand); });
    t.setAttribute("aria-pressed", String(also));
    t.disabled = !also && (!extraZone(cand) || isPrimary(cand) || (assignmentEnabled() && !assignmentReady(cand)));
    if (!extraZone(cand)) t.title = tx("walk.sheet.need_zone");
    row.appendChild(b);
    row.appendChild(t);
    var assigned = photoAssignmentControl(cand);
    var extraClass = also ? classReviewBox(cand) : null;
    if (!assigned && !extraClass) return row;
    var group = el("div", "walk-form__part");
    group.appendChild(row);
    if (assigned) group.appendChild(assigned);
    if (extraClass) group.appendChild(extraClass);
    return group;
  }

  /** Модель предлагает кадры; выбранная человеком привязка хранится отдельно. */
  function assignmentEnabled() { return recognizing() && f.found && f.found.length > 1; }

  function primaryPhotoCandidate() {
    if (f.picked) return f.picked;
    if (!f.manualPhotoCandidate || f.manualPhotoCandidate.code !== f.code) {
      f.manualPhotoCandidate = { code: f.code, frame_indices: null, frame_count: 0 };
    }
    return f.manualPhotoCandidate;
  }

  function validFrameIndices(value, count) {
    if (!Array.isArray(value)) return null;
    var seen = [];
    for (var i = 0; i < value.length; i++) {
      var n = value[i];
      if (typeof n !== "number" || Math.floor(n) !== n || n < 0 || n >= count || seen.indexOf(n) !== -1) return null;
      seen.push(n);
    }
    return seen;
  }

  function frameAssignment(cand) {
    var refs = readyPhotos().map(function (p) { return p.ref; });
    var snapshot = JSON.stringify({ words: f.words.trim(), photos: refs });
    var key = String(f.findId || 0) + ":" + snapshot;
    if (cand.photoAssignment && cand.photoAssignment.key === key) return cand.photoAssignment;
    var source = refs.filter(function (ref, i) { return refs.indexOf(ref) === i; });
    var modelRefs = Array.isArray(cand.frame_refs) ? cand.frame_refs.slice() : [];
    var count = cand.frame_count;
    if (typeof count !== "number" || Math.floor(count) !== count || count < 0 || count !== modelRefs.length) {
      count = 0; modelRefs = [];
    }
    var raw = validFrameIndices(cand.frame_indices, count);
    var proposed = raw ? raw.map(function (i) { return source.indexOf(modelRefs[i]); }) : [];
    if (proposed.some(function (i) { return i < 0; })) proposed = [];
    cand.photoAssignment = {
      key: key, source_photos: source, model_source_photos: modelRefs,
      model_frame_indices: raw,
      assigned_frame_indices: snapshot === f.asked ? proposed : [], confirmed: false,
    };
    return cand.photoAssignment;
  }

  function assignmentReady(cand) {
    var state = frameAssignment(cand);
    return state.confirmed && state.assigned_frame_indices.length > 0;
  }

  function assignmentPayload(cand) {
    var state = frameAssignment(cand);
    return {
      source_photos: state.source_photos.slice(), model_source_photos: state.model_source_photos.slice(),
      model_frame_indices: state.model_frame_indices ? state.model_frame_indices.slice() : null,
      assigned_frame_indices: state.assigned_frame_indices.slice(), confirmed: state.confirmed,
    };
  }

  function assignedPhotos(cand) {
    var state = frameAssignment(cand);
    return state.assigned_frame_indices.map(function (i) { return state.source_photos[i]; });
  }

  function photoAssignmentControl(cand) {
    if (!assignmentEnabled()) return null;
    var state = frameAssignment(cand);
    var box = section(tx("walk.sheet.photo_assignment.title"), tx("walk.sheet.photo_assignment.hint"));
    box.setAttribute("data-photo-assignment", cand.code);
    state.source_photos.forEach(function (ref, index) {
      var label = el("label", "walk-option");
      var input = document.createElement("input");
      input.type = "checkbox";
      input.setAttribute("data-frame-index", String(index));
      input.checked = state.assigned_frame_indices.indexOf(index) !== -1;
      input.addEventListener("change", function () {
        state.assigned_frame_indices = state.assigned_frame_indices.filter(function (i) { return i !== index; });
        if (input.checked) state.assigned_frame_indices.push(index);
        state.assigned_frame_indices.sort(function (a, b) { return a - b; });
        state.confirmed = false;
        classSelectionChanged();
        redraw("item", "level", "footer");
      });
      label.appendChild(input);
      var photo = readyPhotos().filter(function (p) { return p.ref === ref; })[0];
      if (photo && W.photo.thumb) label.appendChild(W.photo.thumb(photo));
      label.appendChild(el("span", null, tx("walk.sheet.photo_assignment.frame", { n: index + 1 })));
      box.appendChild(label);
    });
    var label = el("label", "walk-option");
    var confirm = document.createElement("input");
    confirm.type = "checkbox";
    confirm.setAttribute("data-photo-confirm", "");
    confirm.checked = state.confirmed;
    confirm.disabled = !state.assigned_frame_indices.length;
    confirm.addEventListener("change", function () {
      state.confirmed = confirm.checked;
      classSelectionChanged();
      if (confirm.checked && classSelected(cand)) requestClass(cand);
      redraw("item", "level", "footer");
    });
    label.appendChild(confirm);
    label.appendChild(el("span", null, tx("walk.sheet.photo_assignment.confirm")));
    box.appendChild(label);
    return box;
  }

  /** Равенство кандидатов: известная пара «пункт + зона», либо тот же объект. */
  function sameCandidate(a, b) {
    if (a === b) return true;
    var zone = extraZone(a);
    return !!zone && a.code === b.code && zone === extraZone(b);
  }

  function isPrimary(cand) {
    return cand === f.picked || (!!f.zone && cand.code === f.code && extraZone(cand) === f.zone);
  }

  function isAlso(cand) { return f.also.some(function (c) { return sameCandidate(c, cand); }); }

  function toggleAlso(cand) {
    if (!isAlso(cand) && (!extraZone(cand) || isPrimary(cand) || (assignmentEnabled() && !assignmentReady(cand)))) return;
    f.also = isAlso(cand) ? f.also.filter(function (c) { return !sameCandidate(c, cand); }) : f.also.concat([cand]);
    W.haptic();
    changed();
    if (isAlso(cand)) requestClass(cand);
    redraw("item", "level", "footer");
  }

  /** Отмеченные «тоже» — только у свежего поиска нового нарушения. */
  function extras() {
    if (!recognizing() || !f.found || stale()) return [];
    return f.also.filter(function (c) { return item(c.code) && !isPrimary(c) && !!extraZone(c); });
  }

  /** Неопределённая зона дополнительного кандидата требует выбора человека. */
  function extraZone(cand) {
    var r = cand && cand.resolution;
    var z = r && r.zone && zoneOf(r.zone);
    return z && !z.equipment ? z.code : null;
  }

  function extraLevel(cand) {
    var i = item(cand.code);
    if (i.note) return ADVICE_LEVEL;
    if (i.measure) return "D0";
    if (recognizing()) return classState(cand).level;
    if (i.levels.indexOf(cand.level) !== -1) return cand.level;
    return i.levels.length === 1 ? i.levels[0] : cand.level;
  }

  /**
   * Уточняющий вопрос системы (#1107). Если он о классе первой карточки и
   * варианты годятся для её пункта — кнопки «ответ → класс»: нажатие ставит
   * класс. Иначе — текстом, как раньше. Класс по-прежнему можно поправить ниже.
   */
  function questionBox() {
    var box = el("div", "walk-form__note walk-form__note--info walk-ask");
    box.appendChild(el("p", "walk-ask__q", f.question));
    var top = f.found && f.found[0];
    var it = top && f.code === top.code ? item(top.code) : null;
    var answers = it ? (f.answers || []).filter(function (a) { return it.levels.indexOf(a.level) !== -1; }) : [];
    if (answers.length < 2) return box;
    var row = el("div", "walk-ask__answers");
    answers.forEach(function (a) {
      var on = f.answered === a.text;
      var b = W.button("walk-ask__answer" + (on ? " is-on" : ""), null, function () {
        f.answered = a.text;
        f.level = a.level;
        W.haptic();
        changed();
        redraw.apply(null, ORDER.concat(["footer"]));
      });
      b.setAttribute("aria-pressed", String(on));
      b.appendChild(el("span", "walk-ask__text", a.text));
      b.appendChild(W.level(a.level));
      row.appendChild(b);
    });
    box.appendChild(row);
    return box;
  }

  /** «Где?»: зоны пункта пилюлями, пока зона не названа (D445). */
  function whereRow() {
    var row = el("div", "walk-where");
    row.setAttribute("role", "group");
    row.appendChild(el("span", "walk-where__label", tx("walk.sheet.where")));
    var pills = el("div", "walk-where__pills");
    itemZones(f.code).forEach(function (z) {
      pills.appendChild(W.button("walk-ctx__pill walk-ctx__pill--zone", z.title, function () { setZone(z.code, "pick"); }));
    });
    if (itemZones(f.code).length < realZones().length) {
      pills.appendChild(W.button("walk-ctx__pill walk-ctx__pill--zone", tx("walk.sheet.zone_other"), fullZoneMenu));
    }
    row.appendChild(pills);
    return row;
  }

  /* ── секции ───────────────────────────────────────────────────────── */

  /* ── пункт выбран человеком → класс по его фактам и этому изданию ───── */
  function classState(cand) {
    if (!cand.classReview) {
      cand.classReview = W.classReview.fresh();
      cand.classReview.answer = "";
      cand.classReview.clarifications = [];
      cand.classReview.answerQuestion = "";
      cand.classReview.additionalWords = "";
      cand.classReview.humanText = cand.wording || "";
      cand.classReview.textEdited = false;
      cand.classReview.reading = cand.reading_c == null ? "" : String(cand.reading_c);
      cand.classReview.readingConfirmed = false;
      cand.classReview.readingSource = "model";
    }
    restoreClassFacts(cand, cand.classReview);
    return cand.classReview;
  }

  function classPhotoRefs(cand) {
    if (assignmentEnabled()) return assignmentReady(cand) ? assignedPhotos(cand) : null;
    return readyPhotos().map(function (p) { return p.ref; }).filter(function (ref, i, all) { return all.indexOf(ref) === i; });
  }
  function restoreClassFacts(cand, state) {
    if (state.factsEdited || state.restoredEntry) return;
    var primary = cand === f.picked || cand === f.manualPhotoCandidate;
    var zone = primary ? f.zone : extraZone(cand);
    var refs = classPhotoRefs(cand);
    if (!zone || refs === null) return;
    var words = primary ? f.words.trim() : "";
    var saved = (f.savedClassFacts || []).filter(function (entry) {
      return entry.code === cand.code && entry.zone === zone && entry.words === words &&
        entry.checklist_version === W.state.data.checklist_version &&
        JSON.stringify(entry.photos) === JSON.stringify(refs);
    });
    if (saved.length !== 1) return;
    state.restoredEntry = saved[0];
    state.answer = typeof saved[0].answer === "string" ? saved[0].answer : "";
    state.clarifications = Array.isArray(saved[0].clarifications) ? saved[0].clarifications.filter(function (pair) {
      return pair && typeof pair.question === "string" && typeof pair.answer === "string";
    }) : [];
    state.answerQuestion = saved[0].answer_question || "";
    state.additionalWords = saved[0].additional_words || "";
    if (typeof saved[0].human_text === "string") {state.humanText = saved[0].human_text; state.textEdited = true;}
    state.clarificationScope = saved[0].clarification_scope || null;
    if (!state.readingEdited && saved[0].reading != null) {
      state.reading = String(saved[0].reading);
      state.readingSource = saved[0].reading_source === "human" ? "human" : "model";
      state.readingConfirmed = saved[0].reading_confirmed === true;
      if (primary) {
        f.reading = state.reading;
        f.readingSource = state.readingSource;
        f.readingConfirmed = state.readingConfirmed;
      }
    }
  }
  function classFactDrafts() {
    var facts = (f.savedClassFacts || []).slice();
    if (!recognizing() || !f.code) return facts;
    var candidates = (f.found || []).filter(function (cand) { return !!cand.classReview; });
    if (f.code && candidates.indexOf(primaryClassCandidate()) === -1) candidates.push(primaryClassCandidate());
    candidates.forEach(function (cand) {
      var state = classState(cand);
      var primary = classIsPrimary(cand);
      var zone = primary ? f.zone : extraZone(cand);
      var reading = primary ? f.reading : state.reading;
      if (!state.textEdited && !state.answer && !state.additionalWords && !state.clarifications.length && (reading == null || !String(reading).trim())) return;
      var entry = { code:cand.code, zone:zone || null, checklist_version:W.state.data.checklist_version, answer:state.answer, reading:reading,
        words:primary ? f.words.trim() : "", photos:classPhotoRefs(cand),
        human_text:state.textEdited ? state.humanText : null, additional_words:state.additionalWords, clarifications:state.clarifications, answer_question:state.answerQuestion, clarification_scope:state.clarificationScope,
        reading_source:primary ? f.readingSource : state.readingSource,
        reading_confirmed:primary ? !!f.readingConfirmed : !!state.readingConfirmed };
      // Preserve ambiguous/unmatched facts instead of moving them to another item.
      if (state.restoredEntry) facts = facts.filter(function (old) { return old !== state.restoredEntry; });
      var same = facts.some(function (old) { return JSON.stringify(old) === JSON.stringify(entry); });
      if (!same) facts.push(entry);
    });
    return facts;
  }
  function primaryClassCandidate() { return primaryPhotoCandidate(); }
  function classIsPrimary(cand) { return cand === primaryClassCandidate(); }
  function selectedClassCandidates() {
    if (!recognizing() || !f.code) return [];
    return [primaryClassCandidate()].concat(extras());
  }
  function classReading(cand) {
    var state = classState(cand);
    var primary = classIsPrimary(cand);
    var raw = primary ? f.reading : state.reading;
    var value = raw == null || !String(raw).trim() ? null : parseReading(raw);
    return { raw: raw, value: value, confirmed: primary ? !!f.readingConfirmed : state.readingConfirmed,
      source: primary ? f.readingSource || "human" : state.readingSource };
  }
  function classContext(cand) {
    var state = classState(cand);
    var primary = classIsPrimary(cand);
    var zone = primary ? f.zone : extraZone(cand);
    var reading = classReading(cand);
    var words = [primary ? f.words.trim() : "", state.additionalWords, state.answerQuestion ? "" : state.answer.trim()].filter(Boolean).join("\n");
    var chain = state.clarifications.slice();
    if (state.answerQuestion && state.answer.trim()) chain.push({question:state.answerQuestion, answer:state.answer.trim()});
    var confirmed = !assignmentEnabled() || assignmentReady(cand);
    var photos = assignmentEnabled() ? (confirmed ? assignedPhotos(cand) : [])
      : readyPhotos().map(function (p) { return p.ref; }).filter(function (ref, i, all) { return all.indexOf(ref) === i; });
    var body = { run_id: f.run_id, checklist_version: W.state.data.checklist_version,
      code: cand.code, zone: zone || null, words: words, photos: photos, clarifications:chain,
      reading_c: reading.confirmed ? reading.value : null,
      reading_confirmed: reading.value !== null && reading.confirmed };
    if (body.reading_c !== null) body.reading_source = reading.source;
    var scope = JSON.stringify({run:f.run_id, edition:body.checklist_version, code:cand.code, zone:zone || null,
      words:words, photos:photos, reading:reading, assigned:confirmed});
    var total = words.length + chain.reduce(function (n, pair) {return n + pair.question.length + pair.answer.length;}, 0);
    var blocked = "";
    if ((chain.length || state.answerQuestion) && state.clarificationScope && state.clarificationScope !== scope) blocked = tx("walk.sheet.class_review.review_changed");
    else if (f.run_id !== W.state.data.run_id) blocked = tx("walk.sheet.class_review.context_changed");
    else if (!zone) blocked = tx("walk.sheet.need_zone");
    else if (!confirmed || uploading() || waitingPhotos().length) blocked = tx("walk.sheet.photo_assignment.need");
    else if (reading.raw != null && String(reading.raw).trim() && reading.value === null) blocked = tx("walk.err.reading");
    else if (reading.value !== null && !reading.confirmed) blocked = tx("walk.sheet.class_review.confirm_reading");
    else if (total > 1000 || chain.length > 6 || chain.some(function (pair) {return pair.question.length > 500 || pair.answer.length > 1000;})) blocked = tx("walk.sheet.class_review.facts_limit");
    else if (photos.length > 10) blocked = tx("walk.sheet.class_review.photos_limit");
    return { body: body, scope:scope, total:total, levels: (item(cand.code) || {levels: []}).levels,
      key: JSON.stringify({body: body, reading: reading, assigned: confirmed, search: f.findId || 0,
        currentRun: W.state.data.run_id, blocked: blocked}), blocked: blocked };
  }
  function classSaveContext(cand) {
    var body = classContext(cand).body;
    if (!body.clarifications.length) return null;
    return {clarifications:body.clarifications, run_id:body.run_id, checklist_version:body.checklist_version,
      code:body.code, zone:body.zone, photo_refs:body.photos};
  }
  function classSaveWords(cand) {
    var body = classContext(cand).body;
    return [body.words].concat(body.clarifications.map(function (pair) {return pair.answer;})).filter(Boolean).join("\n");
  }
  function syncClassSelections() {
    if (!f || !recognizing() || !f.code) return;
    selectedClassCandidates().forEach(function (cand) {
      W.classReview.sync(classState(cand), classContext(cand));
    });
    var primary = item(f.code);
    f.level = primary && primary.measure ? "D0" : classState(primaryClassCandidate()).level;
  }
  function classSelectionChanged() {
    if (!f || !recognizing()) return;
    syncClassSelections();
    updateClassPanels();
    saveDraft();
  }
  function classSelected(cand) {
    return !!f && recognizing() && !!f.code &&
      (cand === primaryClassCandidate() || extras().indexOf(cand) !== -1);
  }
  function requestClass(cand) {
    if (!classSelected(cand) || (item(cand.code) || {}).measure || (classIsPrimary(cand) && taken())) return;
    var form = f;
    var context = classContext(cand);
    var requestedState = classState(cand);
    W.classReview.request(requestedState, context, function (key) {
      return f === form && classSelected(cand) && f.run_id === W.state.data.run_id && classContext(cand).key === key;
    }, function () {
      if (f !== form || !classSelected(cand)) return;
      if (["ready", "needs_fact", "not_established"].indexOf(requestedState.status) !== -1 && requestedState.answer.trim()) {
        if (requestedState.answerQuestion) requestedState.clarifications = context.body.clarifications;
        else requestedState.additionalWords = [requestedState.additionalWords, requestedState.answer.trim()].filter(Boolean).join("\n");
        requestedState.answer = "";
        requestedState.answerQuestion = "";
        requestedState.clarificationScope = context.scope;
        if (node) node.querySelectorAll("[data-class-review]").forEach(function (panel) {
          if (panel._candidate === cand) panel.querySelector(".walk-class-review__facts").value = "";
        });
      }
      syncClassSelections();
      updateClassPanels();
      changed();
      redraw("repeat", "footer");
    });
  }
  function classBlocker() {
    if (!recognizing() || !f.code) return null;
    if (f.run_id !== W.state.data.run_id) return "walk.sheet.class_review.context_changed";
    syncClassSelections();
    var candidates = selectedClassCandidates();
    for (var i = 0; i < candidates.length; i++) {
      var cand = candidates[i];
      var reading = classReading(cand);
      if (reading.raw != null && String(reading.raw).trim() && reading.value === null) return "walk.err.reading";
      if (classContext(cand).total > 1000 || classContext(cand).body.clarifications.length > 6) return "walk.sheet.class_review.facts_limit";
      if (classContext(cand).blocked === tx("walk.sheet.class_review.review_changed")) return "walk.sheet.class_review.review_changed";
      if (reading.value !== null && !reading.confirmed) return "walk.sheet.class_review.confirm_reading";
      if ((item(cand.code) || {}).measure || (classIsPrimary(cand) && taken())) continue;
      if (!classState(cand).level) return "walk.sheet.class_review.need_class";
    }
    return null;
  }
  function updateClassPanels() {
    if (!node) return;
    node.querySelectorAll("[data-class-review]").forEach(function (panel) {
      var cand = panel._candidate;
      if (!classSelected(cand)) return;
      renderClassFeedback(panel, cand);
    });
  }
  function renderClassFeedback(panel, cand) {
    var state = classState(cand);
    var feedback = panel.querySelector("[data-class-feedback]");
    feedback.textContent = "";
    var text = state.status === "pending" ? tx("walk.sheet.class_review.pending")
      : state.status === "manual" ? tx("walk.sheet.class_review.manual_active")
      : state.status === "ready" ? tx("walk.sheet.class_review.proposed", {level:state.level})
      : state.status === "needs_fact" ? state.needFact
      : state.status === "not_established" ? tx("walk.sheet.class_review.not_established")
      : state.message || classContext(cand).blocked || tx("walk.sheet.class_review.check_hint");
    feedback.appendChild(el("p", "walk-form__hint", text));
    if (state.status === "needs_fact" && state.provisional) {
      feedback.appendChild(el("p", "walk-form__hint", tx("walk.sheet.class_review.provisional", {level:state.provisional})));
    }
    if (state.clarifications.length) {
      var chainReview = el("details");
      chainReview.appendChild(el("summary", null, tx("walk.sheet.class_review.history")));
      state.clarifications.forEach(function (pair) { chainReview.appendChild(el("p", null, pair.question)); chainReview.appendChild(el("p", null, pair.answer)); });
      feedback.appendChild(chainReview);
    }
    if (classContext(cand).blocked === tx("walk.sheet.class_review.review_changed")) {
      feedback.appendChild(W.button("walk-link", tx("walk.sheet.class_review.reaffirm"), function () {
        state.clarificationScope = classContext(cand).scope;
        state.factsEdited = true;
        classSelectionChanged();
        redraw("item", "level", "footer");
      }));
    }
    if (state.answerQuestion) feedback.appendChild(el("p", "walk-form__hint", state.answerQuestion));
    if (state.reason) feedback.appendChild(el("p", "walk-form__hint", state.reason));
    var zone = classIsPrimary(cand) ? f.zone : extraZone(cand);
    var unmatched = (f.savedClassFacts || []).filter(function (entry) {
      return entry.code === cand.code && entry.zone === zone && entry !== state.restoredEntry &&
        (typeof entry.human_text === "string" || entry.answer || entry.additional_words || (entry.clarifications || []).length || entry.reading != null);
    });
    if (unmatched.length && !state.answer) {
      var recovery = el("details", "walk-form__hint");
      recovery.appendChild(el("summary", null, tx("walk.sheet.class_review.saved_facts")));
      unmatched.forEach(function (entry) {
        recovery.appendChild(el("pre", null, [entry.human_text, entry.additional_words, entry.answer].concat((entry.clarifications || []).map(function (pair) {return pair.question + "\n" + pair.answer;}), [entry.reading]).filter(function (v) { return v != null && v !== ""; }).join("\n")));
        if (typeof entry.human_text === "string" || entry.answer || entry.additional_words || (entry.clarifications || []).length) recovery.appendChild(W.button("walk-link", tx("walk.sheet.class_review.use_saved_facts"), function () {
          if (typeof entry.human_text === "string") {state.humanText = entry.human_text; state.textEdited = true;}
          state.answer = entry.answer || "";
          state.additionalWords = entry.additional_words || "";
          state.answerQuestion = entry.answer_question || "";
          state.clarifications = entry.clarifications || [];
          state.clarificationScope = classContext(cand).scope;
          state.factsEdited = true;
          classSelectionChanged();
          redraw("item", "level", "footer");
        }));
      });
      feedback.appendChild(recovery);
    }
    if (classIsPrimary(cand) && f.legacyLevel && !state.level) {
      feedback.appendChild(el("p", "walk-form__hint", tx("walk.sheet.class_review.draft_level", {level:f.legacyLevel})));
    }
    var check = panel.querySelector("[data-class-check]");
    check.disabled = state.status === "pending" || !!classContext(cand).blocked;
    panel.querySelectorAll("[data-manual-class]").forEach(function (button) {
      var on = state.manualMode && state.level === button.dataset.manualClass;
      button.setAttribute("aria-pressed", String(on));
      button.classList.toggle("is-on", on);
    });
  }
  function addExtraReadingControls(box, cand) {
    var state = classState(cand);
      var numberLabel = el("label", "walk-form__hint", tx("walk.sheet.reading"));
      var number = el("input", "walk-input");
      number.inputMode = "decimal";
      number.value = state.reading;
      number.setAttribute("data-extra-reading", "");
      number.addEventListener("input", function () {
        state.reading = number.value;
        state.readingSource = "human";
        state.readingEdited = true;
        state.readingConfirmed = false;
        var confirm = box.querySelector("[data-extra-reading-confirm]");
        confirm.checked = false;
        confirm.disabled = parseReading(number.value) === null;
        classSelectionChanged();
        redraw("footer");
      });
      numberLabel.appendChild(number);
      box.appendChild(numberLabel);
      var readingLabel = el("label", "walk-option");
      var readingConfirm = document.createElement("input");
      readingConfirm.type = "checkbox";
      readingConfirm.checked = state.readingConfirmed;
      readingConfirm.disabled = parseReading(state.reading) === null;
      readingConfirm.setAttribute("data-extra-reading-confirm", "");
      readingConfirm.addEventListener("change", function () {
        state.readingConfirmed = readingConfirm.checked;
        classSelectionChanged();
        if (readingConfirm.checked) requestClass(cand);
        redraw("footer");
      });
      readingLabel.appendChild(readingConfirm);
      readingLabel.appendChild(el("span", null, tx("walk.sheet.class_review.reading_checked")));
      box.appendChild(readingLabel);
  }
  function extraText(cand) { return classState(cand).humanText; }
  function extraTextEditor(cand) {
    var state = classState(cand);
    var label = el("label", "walk-form__hint", tx("walk.sheet.extra_text"));
    var area = el("textarea", "walk-area");
    area.rows = 4;
    area.maxLength = 1000;
    area.value = state.humanText;
    area.setAttribute("data-extra-text", cand.code);
    area.addEventListener("input", function () {
      state.humanText = area.value;
      state.textEdited = true;
      changed();
      redraw("footer");
    });
    label.appendChild(area);
    label.appendChild(el("p", "walk-form__hint", tx("walk.sheet.text_model_review")));
    return label;
  }
  function classReviewBox(cand) {
    if ((item(cand.code) || {}).measure) {
      var info = section(tx("walk.sheet.level"));
      info.appendChild(el("p", "walk-form__hint", tx("walk.sheet.level_only", {level:"D0"})));
      if (!classIsPrimary(cand)) {addExtraReadingControls(info, cand); info.appendChild(extraTextEditor(cand));}
      return info;
    }
    var state = classState(cand);
    W.classReview.sync(state, classContext(cand));
    var box = section(tx("walk.sheet.level"));
    box.setAttribute("data-class-review", cand.code);
    box._candidate = cand;
    var feedback = el("div");
    feedback.setAttribute("data-class-feedback", "");
    feedback.setAttribute("role", "status");
    box.appendChild(feedback);
    if (!classIsPrimary(cand)) {addExtraReadingControls(box, cand); box.appendChild(extraTextEditor(cand));}
    var label = el("label", "walk-form__hint", tx("walk.sheet.class_review.facts"));
    var facts = el("textarea", "walk-area walk-class-review__facts");
    facts.rows = 2;
    facts.maxLength = 1000;
    facts.value = state.answer;
    facts.addEventListener("input", function () {
      if (!state.answerQuestion && state.needFact) {
        state.answerQuestion = state.needFact.trim();
        state.clarificationScope = classContext(cand).scope;
      }
      state.answer = facts.value;
      state.factsEdited = true;
      classSelectionChanged();
      redraw("repeat", "footer");
    });
    label.appendChild(facts);
    box.appendChild(label);
    var check = W.button("walk-link", tx("walk.sheet.class_review.check"), function () {
      state.manualMode = false;
      requestClass(cand);
      redraw("item", "level", "footer");
    });
    check.setAttribute("data-class-check", "");
    box.appendChild(check);
    if (!state.manualMode) {
      box.appendChild(W.button("walk-link", tx("walk.sheet.class_review.manual"), function () {
        W.classReview.enterManual(state, classContext(cand));
        syncClassSelections();
        changed();
        redraw("item", "level", "footer");
      }));
    } else {
      var seg = el("div", "walk-seg");
      (item(cand.code) || {levels:[]}).levels.forEach(function (level) {
        var button = W.button("walk-seg__opt walk-seg__opt--" + level.toLowerCase(), level, function () {
          W.classReview.chooseManual(state, classContext(cand), level);
          syncClassSelections();
          changed();
          updateClassPanels();
          redraw("repeat", "footer");
        });
        button.dataset.manualClass = level;
        seg.appendChild(button);
      });
      box.appendChild(seg);
    }
    renderClassFeedback(box, cand);
    return box;
  }

  var draw = {
    context: function () {
      var row = el("div", "walk-ctx");
      if (!f.n && !isMeasure()) {
        var kind = KINDS.filter(function (pair) { return pair[0] === f.mode; })[0];
        row.appendChild(W.hinted(W.button("walk-ctx__pill", tx(kind[1]), kindMenu), "kind"));
      }
      // У нового нарушения зона — часть результата поиска «пункт · зона» (D445),
      // отдельной пилюли над формой нет.
      if (!recognizing()) {
        var z = zoneOf(f.zone);
        var zb = W.hinted(W.button("walk-ctx__pill walk-ctx__pill--zone" + (z ? "" : " is-empty"),
          (z ? z.title : tx("walk.sheet.pick_zone")), zoneMenu), "zonepill");
        zb.setAttribute("aria-label", tx("walk.sheet.zone") + ": " + (z ? z.title : tx("walk.sheet.pick_zone")));
        row.appendChild(zb);
      }
      var box = el("div", "walk-ctx__box");
      box.appendChild(row);
      if (isMeasure() && !f.n) box.appendChild(el("p", "walk-form__hint", tx("walk.sheet.measure_hint")));
      if (isAdvice() && !f.n) box.appendChild(el("p", "walk-form__hint", tx("walk.sheet.advice_hint")));
      if (unusual()) box.appendChild(el("p", "walk-form__note", tx("walk.sheet.unusual")));
      return box;
    },

    photos: function () {
      var hint = f.photos.length ? null : isAdvice() ? tx("walk.sheet.photos_optional")
        : isMeasure() ? tx("walk.sheet.photos_measure") : null;
      var box = section(f.photos.length || !recognizing() ? tx("walk.sheet.photos") : null, hint);
      var hero = !f.photos.length && recognizing();
      box.appendChild(W.photo.block(f.photos, {
        hero: hero,
        onFiles: addFiles,
        onRetry: function (p) { send(p, p.file); redraw("photos", "item", "footer"); },
        onRemove: removePhoto,
      }));
      return box;
    },

    words: function () {
      if (!recognizing()) return null;
      var box = section(tx("walk.sheet.words"));
      var area = el("textarea", "walk-area walk-area--words");
      area.rows = 2;
      area.maxLength = 1000;
      area.placeholder = tx("walk.sheet.words_hint");
      area.value = f.words;
      area.addEventListener("input", function () {
        var was = stale();
        f.words = area.value;
        changed();
        classSelectionChanged();
        if (was !== stale() || assignmentEnabled()) redraw("item", "level", "footer");
      });
      box.appendChild(area);
      // Голос (D652): рассказ в пустое поле сразу запускает поиск пункта — то же, что «Найти пункт».
      var voice = W.voiceBar(area, function (_text, wasEmpty) {
        if (wasEmpty && recognizing() && !f.code && !f.finding) find();
      });
      if (voice) box.appendChild(voice);
      return box;
    },

    item: function () {
      if (recognizing()) return found();
      var box = section(isMeasure() ? tx("walk.sheet.item_measure") : isAdvice() ? tx("walk.sheet.item_advice") : tx("walk.sheet.item"));
      var chosen = item(f.code);
      if (!chosen) {
        box.appendChild(W.hinted(W.button("walk-btn walk-btn--pick", tx("walk.sheet.pick_item"), itemMenu), "pickitem"));
        return box;
      }
      var card = el("div", "walk-choice");
      var line = el("div", "walk-choice__line");
      var kind = isAdvice() ? "advice" : chosen.measure ? "info" : "violation";
      if (!chosen.note) line.appendChild(el("span", "walk-choice__code walk-item-code--" + kind, chosen.label || chosen.code));
      line.appendChild(el("span", "walk-item-kind walk-item-kind--" + kind, tx("walk.item.kind." + kind)));
      line.appendChild(el("span", "walk-choice__text", chosen.q));
      card.appendChild(line);
      if (chosen.note) card.appendChild(el("p", "walk-form__hint", tx("walk.note.hint")));
      card.appendChild(W.button("walk-link", tx("walk.sheet.change"), itemMenu));
      box.appendChild(card);
      var t = taken();
      if (t) box.appendChild(el("p", "walk-form__note walk-form__note--info", tx("walk.sheet.taken", { n: t.n })));
      var v = isAdvice() && !f.n ? violationHere() : null;
      if (v) box.appendChild(el("p", "walk-form__note walk-form__note--info", tx("walk.sheet.advice_has_violation", { n: v.n })));
      return box;
    },

    reading: function () {
      var none = f.noViolation !== null && f.noViolation !== undefined;
      if (!hasReading() && recognizing() && f.code) {
        var empty = section(tx("walk.sheet.reading"));
        empty.appendChild(W.button("walk-link", tx("walk.sheet.class_review.add_reading"), function () {
          setReading("", "human", false);
          changed();
          redraw("reading", "level", "footer");
          var field = node.querySelector(".walk-input--reading");
          if (field) field.focus({preventScroll:true});
        }));
        return empty;
      }
      if (!hasReading() || (!f.code && !none)) return null;
      var box = section(tx("walk.sheet.reading"), tx("walk.sheet.reading_hint"));
      if (none) {
        // При этом числе нарушения нет (#836): число можно вернуть и пересчитать
        // снова либо начать поиск заново без температуры.
        box.appendChild(el("p", "walk-form__note walk-form__note--info", tx("walk.sheet.reading_none", { value: String(f.noViolation) })));
      }
      var input = el("input", "walk-input walk-input--reading");
      input.type = "text";
      input.inputMode = "decimal";
      input.autocomplete = "off";
      input.value = f.reading;
      input.setAttribute("aria-label", tx("walk.sheet.reading"));
      input.addEventListener("input", function () {
        var was = readingChanged() || readingInvalid();
        f.reading = input.value;
        if (recognizing()) {
          f.readingSource = "human";
          var own = classState(primaryClassCandidate());
          own.readingEdited = true;
          own.reading = input.value;
          own.readingSource = "human";
          own.readingConfirmed = false;
          f.readingConfirmed = false;
          readingConfirm.checked = false;
          readingConfirm.disabled = parseReading(input.value) === null;
          classSelectionChanged();
          redraw("repeat", "footer");
        } else {
          changed();
          if (was !== (readingChanged() || readingInvalid())) redraw("footer");
        }
      });
      box.appendChild(input);
      var readingConfirm;
      if (recognizing()) {
        var checkedLabel = el("label", "walk-option");
        readingConfirm = document.createElement("input");
        readingConfirm.type = "checkbox";
        readingConfirm.checked = !!f.readingConfirmed;
        readingConfirm.disabled = parseReading(f.reading) === null;
        readingConfirm.setAttribute("data-reading-confirm", "");
        readingConfirm.addEventListener("change", function () {
          f.readingConfirmed = readingConfirm.checked;
          classState(primaryClassCandidate()).readingConfirmed = readingConfirm.checked;
          classSelectionChanged();
          if (readingConfirm.checked) requestClass(primaryClassCandidate());
          redraw("repeat", "footer");
        });
        checkedLabel.appendChild(readingConfirm);
        checkedLabel.appendChild(el("span", null, tx("walk.sheet.class_review.reading_checked")));
        box.appendChild(checkedLabel);
      }
      if (none && recognizing()) {
        box.appendChild(W.button("walk-link", tx("walk.sheet.reading_reset"), function () {
          setReading(null);
          redraw.apply(null, ORDER.concat(["footer"]));
        }));
      }
      return box;
    },

    level: function () {
      var it = item(f.code);
      if (!it || isMeasure() || isAdvice() || taken()) return null;
      if (recognizing()) return classReviewBox(primaryClassCandidate());
      var box = section(tx("walk.sheet.level"));
      if (it.levels.length === 1) {
        box.appendChild(el("p", "walk-form__hint", tx("walk.sheet.level_only", { level: it.levels[0] })));
        return box;
      }
      var seg = W.hinted(el("div", "walk-seg"), "level");
      it.levels.forEach(function (lv) {
        var on = f.level === lv;
        var b = W.button("walk-seg__opt walk-seg__opt--" + lv.toLowerCase() + (on ? " is-on" : ""), lv, function () {
          f.level = lv;
          W.haptic();
          changed();
          redraw("level", "repeat", "footer");
        });
        b.setAttribute("aria-pressed", on ? "true" : "false");
        seg.appendChild(b);
      });
      box.appendChild(seg);
      return box;
    },

    text: function () {
      if (taken() || (recognizing() && !f.code)) return null;
      var label = isMeasure() ? "walk.sheet.text_measure" : isAdvice() ? "walk.sheet.text_advice" : "walk.sheet.text";
      var box = section(tx(label));
      var area = el("textarea", "walk-area");
      area.rows = 3;
      area.maxLength = 1000;
      area.placeholder = tx(label + "_hint");
      area.value = f.text;
      area.setAttribute("data-finding-text", "");
      area.addEventListener("input", function () {
        var was = !!f.text.trim();
        f.text = area.value;
        f.textAuto = false;
        changed();
        // У рекомендации текст обязателен: кнопка оживает с первым словом.
        if ((isAdvice() || !f.n) && was !== !!f.text.trim()) redraw("footer");
      });
      box.appendChild(area);
      if (!f.n && !isAdvice() && !isMeasure()) box.appendChild(el("p", "walk-form__hint", tx("walk.sheet.text_model_review")));
      var voice = W.voiceBar(area);
      if (voice) box.appendChild(voice);
      // Модель вписала рассуждение вместо находки (#970): пока текст её, а не
      // аудитора, — предупреждение под полем. Запись не меняется и не блокируется.
      var flags = (f.textAuto && f.picked && f.picked.flags) || [];
      if (flags.indexOf(ASIDE_FLAG) !== -1) box.appendChild(el("p", "walk-form__hint walk-form__hint--warn", tx("walk.sheet.text_aside")));
      var bar = W.translateBar(area);
      if (bar) box.appendChild(bar);
      return box;
    },

    comment: function () {
      if (taken() || isMeasure() || isAdvice() || (recognizing() && !f.code)) return null;
      var box = section(f.commentOpen ? tx("walk.sheet.comment") : null);
      if (!f.commentOpen) {
        box.appendChild(W.button("walk-link walk-link--add", tx("walk.sheet.comment_add"), function () {
          f.commentOpen = true;
          redraw("comment");
          var a = node.querySelector(".walk-area--comment");
          if (a) {
            a.focus({ preventScroll: true });
            a.scrollIntoView({ block: "nearest" });
          }
        }));
        return box;
      }
      var area = el("textarea", "walk-area walk-area--comment");
      area.rows = 3;
      area.maxLength = 1000;
      area.value = f.comment;
      area.setAttribute("aria-label", tx("walk.sheet.comment"));
      area.addEventListener("input", function () { f.comment = area.value; changed(); });
      box.appendChild(area);
      if (!f.n && !isAdvice() && !isMeasure()) box.appendChild(el("p", "walk-form__hint", tx("walk.sheet.text_model_review")));
      var voice = W.voiceBar(area);
      if (voice) box.appendChild(voice);
      var bar = W.translateBar(area);
      if (bar) box.appendChild(bar);
      return box;
    },

    repeat: function () {
      if (!repeatOffered() && !(f.n && f.repeat)) return null;
      var box = section(null);
      var label = el("label", "walk-check" + (f.repeat ? " is-on" : ""));
      var box2 = el("input");
      box2.type = "checkbox";
      box2.checked = !!f.repeat;
      box2.addEventListener("change", function () {
        f.repeat = box2.checked;
        W.haptic();
        changed();
        redraw("repeat");
      });
      label.appendChild(box2);
      var words = el("span", "walk-check__words");
      words.appendChild(el("span", "walk-check__title", tx("walk.sheet.repeat")));
      words.appendChild(el("span", "walk-check__hint", tx("walk.sheet.repeat_hint")));
      label.appendChild(words);
      box.appendChild(label);
      return box;
    },

    danger: function () {
      if (!f.n) return null;
      var box = section(null);
      if (W.split) {
        var split = W.button("walk-link", tx("walk.split.open"), function () {
          if (dirty()) { W.toast(tx("walk.split.save_first"), "warn"); return; }
          var source = f.source_record; close(true); W.split.open(source);
        });
        box.appendChild(split);
      }
      if (!f.confirmDelete) {
        box.appendChild(W.button("walk-link walk-link--danger", tx("walk.sheet.delete"), function () {
          f.confirmDelete = true;
          redraw("danger");
        }));
        return box;
      }
      box.appendChild(el("p", "walk-form__note", tx("walk.sheet.delete_confirm")));
      var row = el("div", "walk-row");
      row.appendChild(W.button("walk-btn walk-btn--danger", tx("walk.sheet.delete_yes"), function () {
        submit([{ op: "drop", n: f.n }]);
      }));
      row.appendChild(W.button("walk-btn", tx("walk.sheet.cancel"), function () {
        f.confirmDelete = false;
        redraw("danger");
      }));
      box.appendChild(row);
      return box;
    },

    footer: function () {
      var box = el("div", "walk-sheet__foot");
      if (f.confirmClose) {
        box.appendChild(el("p", "walk-form__note", tx("walk.sheet.discard")));
        var row = el("div", "walk-row");
        row.appendChild(W.button("walk-btn walk-btn--danger", tx("walk.sheet.discard_yes"), function () {
          if (!f.n) W.local.drop(draftKey());
          else if (W.editDraft) W.editDraft.clear(f);
          f.photos.forEach(function (p) { (p.receiptIds || (p.entryId ? [p.entryId] : [])).forEach(function (id) { W.offline.remove(id); }); });
          close(true);
        }));
        row.appendChild(W.button("walk-btn", tx("walk.sheet.cancel"), function () {
          f.confirmClose = false;
          redraw("footer");
        }));
        box.appendChild(row);
        return box;
      }
      if (f.error) box.appendChild(el("p", "walk-form__error", f.error));
      if (recognizing() && !f.code && !hasNoViolation()) {
        var blocked = findBlocker();
        var go = W.hinted(W.button("walk-mark walk-mark--find", f.finding ? tx("walk.sheet.finding_short") : tx("walk.sheet.find"), find), "find");
        go.disabled = !!blocked || !!f.finding;
        box.appendChild(go);
        if (blocked) box.appendChild(el("p", "walk-sheet__why", tx(blocked)));
        return box;
      }
      var why = blocker();
      var recheck = !f.n && !recognizing() && readingChanged() && !readingInvalid();
      var label = f.saving ? tx("walk.sheet.saving")
        : f.finding ? tx("walk.sheet.rechecking")
        : recheck ? tx("walk.sheet.recheck")
        : extras().length ? tx("walk.sheet.save_n", { n: extras().length + 1 })
        : taken() ? tx("walk.sheet.add_photos") : tx("walk.sheet.save");
      var save = W.hinted(W.button("walk-mark", label, save_), "save");
      save.disabled = !!why || f.saving || !!f.finding;
      box.appendChild(save);
      if (why && !f.saving) box.appendChild(el("p", "walk-sheet__why", tx(why)));
      return box;
    },
  };

  /** Что нашла система: карточки предложений, выбранное — сверху. */
  function found() {
    var box = section(f.found || f.finding || f.code ? tx("walk.sheet.found") : null);
    if (f.finding) {
      box.appendChild(el("p", "walk-found__wait", tx("walk.sheet.finding")));
      if (f.preview && f.preview.length) {
        box.appendChild(el("p", "walk-found__preview", tx("walk.sheet.preview")));
        var early = el("div", "walk-found");
        f.preview.forEach(function (cand) { early.appendChild(proposal(cand, pickPreview)); });
        box.appendChild(early);
      }
      return box;
    }
    if (f.findError) box.appendChild(el("p", "walk-form__error", f.findError));
    var list = el("div", "walk-found");
    (f.found || []).forEach(function (cand) { list.appendChild(proposal(cand)); });
    var manual = item(f.code);
    var fromList = (f.found || []).some(function (c) { return f.picked ? c === f.picked : isPrimary(c); });
    if (manual && !fromList) list.appendChild(proposal({ code: f.code, level: f.level, zone: f.zone, resolution: { zone: f.zone } }));
    if (list.childNodes.length) box.appendChild(list);
    if (f.found && f.found.length && !f.code) box.appendChild(el("p", "walk-form__hint", tx("walk.sheet.class_review.choose_item")));
    if (f.code && !f.zone && item(f.code) && !isAdvice() && !isMeasure()) box.appendChild(whereRow());
    if (f.found && !f.found.length && !hasNoViolation()) box.appendChild(el("p", "walk-form__note", tx("walk.sheet.found_none")));
    if (f.question && !recognizing()) box.appendChild(questionBox());
    if (stale()) {
      var again = el("p", "walk-form__note walk-form__note--info");
      again.appendChild(document.createTextNode(tx("walk.sheet.found_stale") + " "));
      again.appendChild(W.button("walk-link", tx("walk.sheet.find_again"), find));
      box.appendChild(again);
    }
    box.appendChild(W.button("walk-link", tx("walk.sheet.pick_manual"), itemMenu));
    var t = taken();
    if (t) box.appendChild(el("p", "walk-form__note walk-form__note--info", tx("walk.sheet.taken", { n: t.n })));
    return box;
  }

  // Имя пометки — из `src/recognize/rules_check.py` (`SERVICE_ASIDE`).
  var ASIDE_FLAG = "служебная-оговорка";
  var ORDER = ["context", "photos", "words", "item", "text", "comment", "reading", "level", "repeat", "danger"];

  function redraw() {
    var names = Array.prototype.slice.call(arguments);
    names.forEach(function (name) {
      var holder = parts[name];
      if (!holder) return;
      holder.textContent = "";
      var made = draw[name]();
      if (made) holder.appendChild(made);
    });
  }

  /* ── сохранение ───────────────────────────────────────────────────── */

  /**
   * Что предложила система до решения человека (T164, D077): первая карточка,
   * как у бота, — по ней считается, что аудитор поправил. Пункт вручную без
   * поиска — предложения не было вовсе.
   */
  function suggested() {
    if (!f.found || !f.found.length || stale()) return null;
    var top = f.found[0];
    return { code: top.code, level: top.level, zone: top.zone, confidence: top.confidence, via: f.via };
  }

  /** Число для записи: пустое поле — null (замера нет). */
  function readingValue() {
    if (!hasReading() || f.reading.trim() === "") return null;
    return parseReading(f.reading);
  }

  /** «Тоже»-записи (D593): свои подтверждённые кадры; слова не учат синоним второго пункта. */
  function extraOps() {
    return extras().map(function (c) {
      return {
        op: "add", zone: extraZone(c), code: c.code, level: extraLevel(c), text: extraText(c).trim(),
        comment: "", repeat: false, photos: assignedPhotos(c), words: classSaveWords(c), also: true,
        photo_assignment: assignmentPayload(c),
        class_context: classSaveContext(c),
        suggested: { code: c.code, level: c.level, zone: c.zone, confidence: c.confidence, via: f.via },
        reading_c: classReading(c).confirmed ? classReading(c).value : null,
      };
    });
  }

  function ops() {
    var assigned = assignmentEnabled() ? primaryPhotoCandidate() : null;
    var photos = assigned ? assignedPhotos(assigned) : readyPhotos().map(function (p) { return p.ref; });
    var refs = readyPhotos().filter(function (p) { return p.fresh && photos.indexOf(p.ref) !== -1; }).map(function (p) { return p.ref; });
    var t = taken();
    if (t) return refs.map(function (ref) {
      var body = { op: "attach", n: t.n, ref: ref };
      if (assigned) {
        body.photo_assignment = assignmentPayload(assigned);
        body.photo_assignment.assigned_frame_indices = [body.photo_assignment.source_photos.indexOf(ref)];
      }
      return body;
    }).concat(extraOps());
    if (!f.n) {
      return [{
        op: "add", zone: f.zone, code: f.code, level: isAdvice() ? ADVICE_LEVEL : f.level, text: f.text.trim(),
        comment: f.comment.trim(), repeat: !!f.repeat && repeatOffered(),
        photos: photos,
        photo_assignment: assigned ? assignmentPayload(assigned) : null,
        words: recognizing() ? classSaveWords(primaryClassCandidate()) : f.words.trim(),
        class_context: recognizing() ? classSaveContext(primaryClassCandidate()) : null,
        suggested: suggested(), reading_c: readingValue(),
        hint_codes: f.hintCodes || [],
      }].concat(extraOps());
    }
    var o = f.original;
    var edit = { op: "edit", n: f.n };
    var any = false;
    if (f.code !== o.code) { edit.code = f.code; any = true; }
    if (f.level !== o.level) { edit.level = f.level; any = true; }
    if (f.zone !== o.zone) { edit.zone = f.zone; any = true; }
    if (f.text.trim() !== o.text) { edit.text = f.text.trim(); any = true; }
    if (f.comment.trim() !== o.comment) { edit.comment = f.comment.trim(); any = true; }
    if (!!f.repeat !== !!o.repeat) { edit.repeat = !!f.repeat; any = true; }
    if (hasReading() && readingValue() !== o.reading) { edit.reading_c = readingValue(); any = true; }
    if (refs.length || f.removed.length) {
      edit.new_refs = refs;
      edit.remove_photos = f.removed.slice();
      any = true;
    }
    if (!any) return [];
    return [W.editDraft ? W.editDraft.body(f, edit) : edit];
  }

  function save_() {
    if (blocker()) return;
    if (!f.n && !recognizing() && readingChanged()) {
      // Число поправлено — это не запись, а пересчёт предложения (#836): новое
      // предложение ждёт «Сохранить». Стёртое поле — «замера нет», пересчитывать нечего.
      var fixed = readingValue();
      if (fixed !== null) { find(fixed); return; }
    }
    var list = ops();
    if (!list.length) { if (f.n && W.editDraft) W.editDraft.clear(f); close(true); return; }
    submit(list);
  }

  /** «Записано: <зона>»; зона не та, что на экране, — со ссылкой «Перейти» (D445). */
  function savedToast(zoneCode) {
    var z = zoneOf(zoneCode);
    if (!z) { W.toast(tx("walk.sheet.saved"), "ok"); return; }
    var text = tx("walk.sheet.saved_in", { zone: z.title });
    if (zoneCode === W.state.open || !W.goZone) { W.toast(text, "ok"); return; }
    W.toast(text, "ok", { label: tx("walk.sheet.saved_go"), run: function () { W.goZone(zoneCode); } });
  }

  function submit(list) {
    var form = f;
    var runId = form.run_id;
    f.saving = true;
    f.error = null;
    redraw("footer");
    var last = null;
    var confirmed = [];
    var at = f.zone;
    var beginning = Promise.resolve();
    if (form.reconcile) beginning = W.post(W.urls.data, {}).then(function (res) {
      if (!res.ok || f !== form || W.state.data.run_id !== runId || !res.body || res.body.run_id !== runId) throw new Error(tx("walk.err.run_changed"));
      last = res.body;
      (form.submitted_ops || []).forEach(function (attempt) {
        var matches = matching(last, attempt.body, attempt);
        if (attempt.confirmed_n && !matches.some(function (record) { return record.n === attempt.confirmed_n; })) throw new Error(tx("walk.sheet.save_conflict"));
        if (/^D[1-3]$/.test(attempt.body.level) && records(last, attempt.body).length && !matches.length) throw new Error(tx("walk.sheet.save_conflict"));
        if (!/^D[1-3]$/.test(attempt.body.level) && !matches.length && records(last, attempt.body).some(function (record) { return (attempt.before_ids || []).indexOf(record.n) === -1; })) throw new Error(tx("walk.sheet.save_conflict"));
      });
      W.apply(last, true);
    });
    var chain = list.reduce(function (p, body) {
      return p.then(function () {
        if (f !== form || W.state.data.run_id !== runId) throw new Error(tx("walk.err.run_changed"));
        if (body.op === "add") {
          form.submitted_ops = form.submitted_ops || [];
          if (!form.submitted_ops.some(function (attempt) { return JSON.stringify(attempt.body) === JSON.stringify(body); })) {
            form.submitted_ops.push({body: body, before_ids: records(last || W.state.data, body).map(function (record) { return record.n; })});
          }
          saveDraft();
        }
        return writeOperation(body).then(function (res) {
          if (!res) return;
          if (!res.ok) throw new Error((res.body && res.body.message) || tx("walk.error"));
          var refs = body.op === "add" ? body.photos || [] : body.op === "attach" ? [body.ref] : body.op === "edit" ? body.new_refs || [] : [];
          if (!res.body || res.body.run_id !== runId || f !== form || W.state.data.run_id !== runId) throw new Error(tx("walk.err.run_changed"));
          if (body.op === "add") {
            var recorded = matching(res.body, body, attemptFor(body))[0];
            form.submitted_ops.forEach(function (attempt) { if (JSON.stringify(attempt.body) === JSON.stringify(body) && recorded) attempt.confirmed_n = recorded.n; });
            saveDraft();
          }
          return accept(res, refs, body);
        });
      });
    }, beginning);
    chain.then(function () {
      if (f !== form || W.state.data.run_id !== runId) return;
      if (!f.n) {
        var remaining = f.photos.filter(function (p) { return !p.ref || confirmed.indexOf(p.ref) === -1; });
        if (!remaining.length) W.local.drop(draftKey());
        else W.local.set(draftKey(), Object.assign({}, W.local.get(draftKey()) || {}, {
          run_id: runId, mode: f.mode, zone: null, code: null, level: null, text: "", comment: "", repeat: false,
          reading: null, words: f.words, photos: remaining.filter(function (p) { return p.ref; }).map(function (p) { return p.ref; }),
          queued: remaining.filter(function (p) { return p.ref; }).map(function (p) { return p.ref; }),
          reconcile: false, submitted_ops: [],
        }));
      } else if (W.editDraft) W.editDraft.clear(form);
      W.haptic("success");
      if (remaining && remaining.length) W.toast(tx("walk.sheet.remaining_material", { n: remaining.length }), "warn");
      else savedToast(at);
      close(true);
      if (last) W.apply(last);
    }, function (err) {
      if (f !== form || W.state.data.run_id !== runId) return;
      W.haptic("error");
      f.saving = false;
      f.reconcile = true; saveDraft();
      f.error = err && err.message && err.message !== "Failed to fetch" ? err.message : tx("walk.err.network");
      // Часть шагов могла пройти — данные экрана подтягиваются заново.
      if (last) W.apply(last, true);
      redraw("footer");
    });

    function accept(res, refs, body) {
      if (f !== form || W.state.data.run_id !== runId || !res.body || res.body.run_id !== runId) return Promise.reject(new Error(tx("walk.err.run_changed")));
      var targets = body && body.op === "add" ? matching(res.body, body, attemptFor(body)) :
        (res.body.zones || []).reduce(function (all, zone) { return all.concat(zone.recorded); }, []).filter(function (record) { return body && record.n === body.n; });
      if (refs.length && !targets.some(function (record) { return refs.every(function (ref) { return record.photos.some(function (p) { return p.ref === ref; }); }); })) return Promise.reject(new Error(tx("walk.sheet.save_conflict")));
      last = res.body;
      refs.forEach(function (ref) { if (confirmed.indexOf(ref) === -1) confirmed.push(ref); });
      if (!form.draftKey || !refs.length || !W.offline.ack) return Promise.resolve();
      return W.offline.list(form.draftKey).then(function (rows) {
        return W.offline.ack(form.draftKey, runId, rows.filter(function (r) { return refs.indexOf(r.uploaded_ref) !== -1; }).map(function (r) { return r.id; }));
      }).then(function () {
        if (form.n && W.editDraft) return W.editDraft.ack(form, refs);
      });
    }

    function attemptFor(body) {
      return (form.submitted_ops || []).filter(function (attempt) { return JSON.stringify(attempt.body) === JSON.stringify(body); })[0];
    }

    function matching(data, body, attempt) {
      return records(data, body).filter(function (record) {
        return sameFacts(record, body) && (/^D[1-3]$/.test(body.level) || !attempt || (attempt.before_ids || []).indexOf(record.n) === -1);
      });
    }

    function writeOperation(body) {
      // A prior step can have succeeded before a later request failed. Use
      // the existing same-point attach path instead of adding it again.
      if (body.op === "add") {
        var candidates = records(last || W.state.data, body);
        var exists = matching(last || W.state.data, body, attemptFor(body))[0];
        if (candidates.length && /^D[1-3]$/.test(body.level) && !exists) return Promise.reject(new Error(tx("walk.sheet.save_conflict")));
        if (!form.reconcile && !/^D[1-3]$/.test(body.level)) exists = null;
        if (exists) {
          return Promise.resolve({ok: true, body: last || W.state.data});
        }
      }
      return W.api.write(W.urls.finding, body, runId);
    }
  }

  function records(data, body) {
    return (data.zones || []).reduce(function (all, zone) {
      return all.concat(zone.recorded.filter(function (record) { return (record.zone || zone.code) === body.zone && record.code === body.code &&
        (/^D[1-3]$/.test(body.level) ? /^D[1-3]$/.test(record.level) : record.level === body.level); }));
    }, []);
  }

  function hasEditDraft() {
    var prefix = f.run_key + "_edit_" + f.n + "_";
    return f.draftKey.indexOf(prefix) === 0 && /^[a-f0-9]{64}$/.test(f.draftKey.slice(prefix.length));
  }

  function sameFacts(record, body) {
    var known = item(body.code);
    var expectedText = body.text || (known && known.q) || "";
    function refs(values) { return values.filter(function (ref, at, all) { return all.indexOf(ref) === at; }).sort().join("|"); }
    return record.level === body.level && record.text === expectedText && (record.comment || "") === (body.comment || "") &&
      (record.words || "") === (body.words || "") && !!record.repeat === !!body.repeat &&
      (record.reading_c == null ? null : record.reading_c) === (body.reading_c == null ? null : body.reading_c) &&
      refs((record.photos || []).map(function (p) { return p.ref; })) === refs(body.photos || []);
  }

  /* ── открыть и закрыть ────────────────────────────────────────────── */

  function close(force) {
    if (!f) return;
    if (!force && dirty() && !f.saving) {
      f.confirmClose = true;
      redraw("footer");
      return;
    }
    if (f.n && W.editDraft) W.editDraft.release(f);
    f = null;
    if (W.voice) W.voice.cancelAll(); // идущая запись голоса выбрасывается, микрофон отпускается
    if (W.menu) W.menu.close();
    // Закрываем клавиатуру до снятия блокировки страницы: иначе iOS меняет
    // позицию обхода вслед за исчезнувшим полем и сохранение «прыгает».
    if (node && node.contains(document.activeElement)) document.activeElement.blur();
    if (node) node.remove();
    node = null;
    document.documentElement.classList.remove("has-sheet");
    window.scrollTo(0, returnScrollY);
    if (W.tg && W.supports("6.1")) {
      W.tg.BackButton.offClick(onBack);
      W.app.syncBack();
    }
    if (W.tg && W.supports("6.2")) W.tg.disableClosingConfirmation();
  }

  /** «Назад» при открытом видоискателе закрывает его, а не форму. */
  function onBack() {
    if (W.photo && W.photo.closeCamera()) return;
    close(false);
  }

  /**
   * Открыть форму.
   *   { mode: "violation" | "advice" | "measure", zone, code, level, repeat } — новая запись
   *     (`zone` — только когда пункт и зона названы явно, как у пункта чек-листа;
   *     иначе `hint` — зона на экране, мягкая подсказка, не зона записи);
   *   { record: <запись из данных>, zone } — правка.
   */
  function open(opts) {
    if (f) close(true);
    var rec = opts.record;
    f = {
      source_record: rec || null,
      run_id: W.state.data.run_id,
      run_key: W.state.data.key,
      draftKey: W.state.data.key + "_draft",
      mode: opts.mode || "violation",
      n: rec ? rec.n : null,
      zone: opts.zone || null,
      // Зона на экране — мягкая подсказка поиску, а не зона записи (D445).
      hint: opts.hint || null,
      code: opts.code || null,
      level: opts.level || null,
      text: "",
      comment: "",
      repeat: !!opts.repeat,
      photos: [],
      removed: [],
      gone: [],
      words: "",
      found: null,
      also: [],
      preset: opts.code || null,
      reading: null,
      readingBase: null,
      noViolation: null,
    };
    if (rec) {
      f.mode = rec.level === "D0" ? "measure" : rec.level === ADVICE_LEVEL ? "advice" : "violation";
      f.code = rec.code;
      f.level = rec.level;
      f.text = rec.text;
      f.comment = rec.comment || "";
      f.repeat = !!rec.repeat;
      f.commentOpen = !!rec.comment;
      f.photos = rec.photos.map(function (p) { return { id: ++seq, ref: p.ref, own: p.own, state: "done" }; });
      f.words = rec.words || "";
      if (rec.reading_c !== null && rec.reading_c !== undefined) setReading(rec.reading_c);
      f.original = { code: rec.code, level: rec.level, zone: opts.zone, text: rec.text, comment: rec.comment || "", repeat: !!rec.repeat, reading: rec.reading_c === undefined ? null : rec.reading_c };
      if (W.editDraft) W.editDraft.init(f, rec);
    } else {
      var draft = loadDraft();
      if (draft && !opts.code && draft.mode === f.mode && (draft.code || draft.words || draft.text || draft.comment || (draft.photos || []).length)) {
        f.zone = draft.zone || f.zone;
        f.code = draft.code;
        f.level = draft.level;
        f.text = draft.text || "";
        f.comment = draft.comment || "";
        f.words = draft.words || "";
        if (draft.reading !== null && draft.reading !== undefined) { f.reading = String(draft.reading); f.readingBase = parseReading(draft.reading); }
        f.savedClassFacts = Array.isArray(draft.class_facts) ? draft.class_facts : [];
        f.readingSource = draft.reading_source === "human" ? "human" : "model";
        f.readingConfirmed = draft.reading_confirmed === true;
        f.commentOpen = !!draft.comment;
        f.repeat = !!draft.repeat;
        f.reconcile = !!draft.reconcile; f.submitted_ops = draft.submitted_ops || [];
        f.photos = (draft.photos || []).map(function (ref) { return { id: ++seq, ref: ref, own: true, state: "done", fresh: true }; });
        f.restored = true;
      } else if (draft && draft.mode === f.mode && (draft.queued || []).length) {
        // Пункт задан явно — черновик не трогаем, но кадры, дошедшие без связи, возвращаем.
        f.photos = draft.queued.map(function (ref) { return { id: ++seq, ref: ref, own: true, state: "done", fresh: true }; });
        f.restored = true;
      }
    }
    if (!rec && f.mode === "violation" && f.code) {
      f.legacyLevel = f.level;
      f.level = null;
    }
    build();
    restoreWaiting();
    if (f.n && W.editDraft) {
      var editForm = f;
      W.editDraft.activate(editForm, function () { changed(); redraw("photos", "footer"); }, function () {return f === editForm;});
    }
  }

  function build() {
    returnScrollY = window.scrollY;
    node = el("div", "walk-sheet");
    node.setAttribute("role", "dialog");
    node.setAttribute("aria-modal", "true");
    node.addEventListener("keydown", function (e) {
      // Enter — то же явное подтверждение, что кнопка. Shift+Enter оставляет
      // перенос строки; завершение ввода через IME записью не считается.
      if (e.key !== "Enter" || e.shiftKey || e.ctrlKey || e.altKey || e.metaKey ||
          e.isComposing || e.keyCode === 229 || e.target.tagName !== "TEXTAREA") return;
      if (blocker() || f.saving || f.finding) return;
      e.preventDefault();
      save_();
    });
    var head = el("header", "walk-sheet__head");
    // «Назад» видна всегда, а не только кнопкой Telegram в его шапке: в
    // браузере её нет вовсе, а в Telegram её не все замечают.
    var back = W.button("walk-sheet__back", "‹ " + tx("walk.sheet.back"), function () { close(false); });
    head.appendChild(back);
    head.appendChild(el("h2", "walk-sheet__title", titleText()));
    node.appendChild(head);
    var body = el("div", "walk-sheet__body");
    if (f.restored) body.appendChild(el("p", "walk-form__note walk-form__note--info", tx("walk.sheet.restored")));
    parts = {};
    ORDER.forEach(function (name) {
      parts[name] = el("div", "walk-sheet__slot");
      body.appendChild(parts[name]);
    });
    node.appendChild(body);
    parts.footer = el("div");
    node.appendChild(parts.footer);
    redraw.apply(null, ORDER.concat(["footer"]));
    recoveryPanel(body);
    if (f.n && W.editDraft) {
      var editRecovery = W.editDraft.panel(f, function () { changed(); redraw.apply(null, ORDER.concat(["footer"])); });
      if (editRecovery) body.appendChild(editRecovery);
    }
    document.body.appendChild(node);
    document.documentElement.classList.add("has-sheet");
    if (W.tg && W.supports("6.1")) {
      W.tg.BackButton.onClick(onBack);
      W.tg.BackButton.show();
    }
    changed();
  }

  W.offline.onUploaded = adopt;
  W.offline.onFailed = uploadFailed;
  W.offline.onTick = retryInMemory;

  W.sheet = { open: open, close: close, isOpen: function () { return !!f; } };
})();
