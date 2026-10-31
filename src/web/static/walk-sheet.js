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
 * сохраняются отдельными записями с теми же кадрами и словами, следом за
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

  function setReading(value) {
    f.reading = value === null || value === undefined ? null : String(value);
    f.readingBase = value === null || value === undefined ? null : value;
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
      return !f.zone || !i.zones.length || i.zones.indexOf(f.zone) !== -1;
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
    // Число после «нарушения нет» поправлено: «Пересчитать» доступно без пункта.
    if (f.noViolation !== null && readingChanged() && !readingInvalid()) return null;
    if (!f.zone) return recognizing() && f.code ? "walk.sheet.need_where" : "walk.sheet.need_zone";
    if (!f.code) return "walk.sheet.need_item";
    if (readingInvalid()) return "walk.err.reading";
    if (isAdvice()) return f.text.trim() ? null : "walk.sheet.need_advice";
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
    if (f.n) return;
    W.local.set(draftKey(), {
      run_id: f.run_id, mode: f.mode, zone: f.zone, code: f.code, level: f.level, text: f.text,
      comment: f.comment, repeat: f.repeat, words: f.words, reading: f.reading,
      photos: readyPhotos().map(function (p) { return p.ref; }),
    });
  }

  function changed() {
    saveDraft();
    if (W.tg && W.supports("6.2")) {
      if (dirty()) W.tg.enableClosingConfirmation(); else W.tg.disableClosingConfirmation();
    }
  }

  /* ── кадры ────────────────────────────────────────────────────────── */

  function addFiles(files) {
    // Кадр новой записи при обрыве связи переживёт закрытие формы: он привязан к черновику.
    var key = f.n ? null : draftKey();
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
    if (!f || f.n || f.run_id !== entry.run_id || draftKey() !== entry.key) return false;
    if (f.gone.indexOf(entry.id) !== -1) return true;
    var p = f.photos.filter(function (x) { return x.entryId === entry.id || x.ref === ref; })[0];
    if (!p) {
      p = { id: ++seq, fresh: true, own: true, draftKey: entry.key, run_id: entry.run_id, mode: entry.mode, url: URL.createObjectURL(entry.blob) };
      f.photos.push(p);
    }
    p.ref = ref;
    p.state = "done";
    p.entryId = null;
    W.photo.remember(ref, p.url);
    changed();
    redraw("photos", "item", "footer");
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
    if (f.n || !W.offline.available()) return;
    var mine = f;
    W.offline.list(draftKey()).then(function (entries) {
      if (f !== mine) return;
      var added = false;
      entries.forEach(function (e) {
        if (e.mode !== f.mode || f.gone.indexOf(e.id) !== -1) return;
        if (f.photos.some(function (x) { return x.entryId === e.id; })) return;
        f.photos.push({
          id: ++seq, state: "waiting", fresh: true, own: true, entryId: e.id, draftKey: e.key, run_id: e.run_id,
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
    if (p.entryId) { f.gone.push(p.entryId); W.offline.remove(p.entryId); }
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
      tags: choices("").map(function (i) { return i.process; }).filter(function (p, at, all) { return p && all.indexOf(p) === at; }),
      list: function (q) {
        return choices(q).map(function (i) {
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
    if (i.measure) f.level = "D0";
    else if (isAdvice() || i.note) f.level = ADVICE_LEVEL;
    else if (cand && i.levels.indexOf(cand.level) !== -1) f.level = cand.level;
    else if (i.levels.length === 1) f.level = i.levels[0];
    else if (i.levels.indexOf(f.level) === -1) f.level = null;
    var before = previousHere(code);
    if (before && !isAdvice() && !f.level && i.levels.indexOf(before.level) !== -1) f.level = before.level;
    if (cand && cand.wording && (!f.text.trim() || f.textAuto)) { f.text = cand.wording; f.textAuto = true; }
    if (cand && cand.reading_c !== null && cand.reading_c !== undefined) setReading(cand.reading_c);
    else if (cand && !f.n) setReading(null);
    W.haptic();
    changed();
    redraw.apply(null, ORDER.concat(["footer"]));
  }

  /* ── система ищет пункт (D330) ─────────────────────────────────────── */

  function find(reading) {
    if (findBlocker() || f.finding) return;
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
      if (!f || f.findId !== mine) return;
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
      if (f.found.length) {
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
      if (!f || f.findId !== mine) return;
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
    W.post(W.urls.hint, { zone_hint: zone, words: asked.words, frames: asked.photos.length }).then(function (res) {
      if (!f || !f.finding || f.findId !== mine || !res.ok) return;
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
    if (cand.level && cand.level !== ADVICE_LEVEL) top.appendChild(W.level(cand.level));
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
    t.disabled = !extraZone(cand) || isPrimary(cand);
    if (!extraZone(cand)) t.title = tx("walk.sheet.need_zone");
    row.appendChild(b);
    row.appendChild(t);
    return row;
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
    if (!extraZone(cand) || isPrimary(cand)) return;
    f.also = isAlso(cand) ? f.also.filter(function (c) { return !sameCandidate(c, cand); }) : f.also.concat([cand]);
    W.haptic();
    redraw("item", "footer");
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
        if (was !== stale()) redraw("item", "footer");
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
        changed();
        if (was !== (readingChanged() || readingInvalid())) redraw("footer");
      });
      box.appendChild(input);
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
      area.addEventListener("input", function () {
        var was = !!f.text.trim();
        f.text = area.value;
        f.textAuto = false;
        changed();
        // У рекомендации текст обязателен: кнопка оживает с первым словом.
        if (isAdvice() && was !== !!f.text.trim()) redraw("footer");
      });
      box.appendChild(area);
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
          waitingPhotos().forEach(function (p) { if (p.entryId) W.offline.remove(p.entryId); });
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
      var recheck = readingChanged() && !readingInvalid();
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
    if (f.code && !f.zone && item(f.code) && !isAdvice() && !isMeasure()) box.appendChild(whereRow());
    if (f.found && !f.found.length && !hasNoViolation()) box.appendChild(el("p", "walk-form__note", tx("walk.sheet.found_none")));
    if (f.question) box.appendChild(questionBox());
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

  /** «Тоже»-записи (D593): те же кадры и слова, синоним по ним не учится — слова про основной пункт. */
  function extraOps() {
    var photos = readyPhotos().map(function (p) { return p.ref; });
    return extras().map(function (c) {
      return {
        op: "add", zone: extraZone(c), code: c.code, level: extraLevel(c), text: (c.wording || "").trim(),
        comment: "", repeat: false, photos: photos, words: f.words.trim(), also: true,
        suggested: { code: c.code, level: c.level, zone: c.zone, confidence: c.confidence, via: f.via },
        reading_c: c.reading_c === undefined ? null : c.reading_c,
      };
    });
  }

  function ops() {
    var refs = readyPhotos().filter(function (p) { return p.fresh; }).map(function (p) { return p.ref; });
    var t = taken();
    if (t) return refs.map(function (ref) { return { op: "attach", n: t.n, ref: ref }; }).concat(extraOps());
    if (!f.n) {
      return [{
        op: "add", zone: f.zone, code: f.code, level: isAdvice() ? ADVICE_LEVEL : f.level, text: f.text.trim(),
        comment: f.comment.trim(), repeat: !!f.repeat && repeatOffered(),
        photos: readyPhotos().map(function (p) { return p.ref; }),
        words: f.words.trim(), suggested: suggested(), reading_c: readingValue(),
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
    var list = refs.map(function (ref) { return { op: "attach", n: f.n, ref: ref }; });
    if (any) list.unshift(edit);
    // Снимать — после того, как новые кадры легли: запись ни на миг без фото.
    return list.concat(f.removed.map(function (ref) { return { op: "detach", n: f.n, ref: ref }; }));
  }

  function save_() {
    if (blocker()) return;
    if (readingChanged()) {
      // Число поправлено — это не запись, а пересчёт предложения (#836): новое
      // предложение ждёт «Сохранить». Стёртое поле — «замера нет», пересчитывать нечего.
      var fixed = readingValue();
      if (fixed !== null) { find(fixed); return; }
    }
    var list = ops();
    if (!list.length) { close(true); return; }
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
    var at = f.zone;
    var chain = list.reduce(function (p, body) {
      return p.then(function () {
        return W.api.write(W.urls.finding, body, runId).then(function (res) {
          if (!res.ok) throw new Error((res.body && res.body.message) || tx("walk.error"));
          last = res.body;
        });
      });
    }, Promise.resolve());
    chain.then(function () {
      if (f !== form || W.state.data.run_id !== runId) return;
      if (!f.n) W.local.drop(draftKey());
      W.haptic("success");
      savedToast(at);
      close(true);
      if (last) W.apply(last);
    }, function (err) {
      if (f !== form || W.state.data.run_id !== runId) return;
      W.haptic("error");
      f.saving = false;
      f.error = err && err.message && err.message !== "Failed to fetch" ? err.message : tx("walk.err.network");
      // Часть шагов могла пройти — данные экрана подтягиваются заново.
      if (last) W.apply(last, true);
      redraw("footer");
    });
  }

  /* ── открыть и закрыть ────────────────────────────────────────────── */

  function close(force) {
    if (!f) return;
    if (!force && dirty() && !f.saving) {
      f.confirmClose = true;
      redraw("footer");
      return;
    }
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
      run_id: W.state.data.run_id,
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
        f.commentOpen = !!draft.comment;
        f.repeat = !!draft.repeat;
        f.photos = (draft.photos || []).map(function (ref) { return { id: ++seq, ref: ref, own: true, state: "done", fresh: true }; });
        f.restored = true;
      } else if (draft && draft.mode === f.mode && (draft.queued || []).length) {
        // Пункт задан явно — черновик не трогаем, но кадры, дошедшие без связи, возвращаем.
        f.photos = draft.queued.map(function (ref) { return { id: ++seq, ref: ref, own: true, state: "done", fresh: true }; });
        f.restored = true;
      }
    }
    build();
    restoreWaiting();
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
    document.body.appendChild(node);
    document.documentElement.classList.add("has-sheet");
    if (W.tg && W.supports("6.1")) {
      W.tg.BackButton.onClick(onBack);
      W.tg.BackButton.show();
    }
    changed();
  }

  W.offline.onUploaded = adopt;
  W.offline.onTick = retryInMemory;

  W.sheet = { open: open, close: close, isOpen: function () { return !!f; } };
})();
