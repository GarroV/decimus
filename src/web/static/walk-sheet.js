/* Мини-апп обхода: форма записи (D312) — нарушение, рекомендация, замер, правка.
 * Как устроена и почему — docs/13-walk-mini-app.md, раздел о форме записи.
 *
 * Нарушение (D330): кадр и пара слов → «Найти пункт» → система (та же, что у
 * бота, `/tg/walk/suggest`) предлагает карточки, верхняя выбрана → человек
 * проверяет и жмёт «Сохранить». Ручной поиск — запасной путь из меню. Зона и
 * вид записи — строкой над формой, выбор — меню снизу (`walk-menu.js`).
 * Рекомендация (D201, класс R) и общая заметка (D314, код NOTE) — без вычета,
 * текст обязателен. Замер (D0) — со стоянки «Печь и холодильники» (D315).
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

  /* ── данные формы ─────────────────────────────────────────────────── */

  function draftKey() { return W.state.data.key + "_draft"; }

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

  function readyPhotos() { return f.photos.filter(function (p) { return p.state === "done"; }); }

  /** Новое нарушение без выбранного пункта: пункт ищет система (D330). */
  function recognizing() { return !f.n && f.mode === "violation"; }

  /** Что мешает спросить систему: без кадра нарушение не разбирается (D078). */
  function findBlocker() {
    if (!readyPhotos().length) return uploading() ? "walk.sheet.need_upload" : "walk.sheet.need_photo";
    if (uploading()) return "walk.sheet.need_upload";
    return null;
  }

  function blocker() {
    // Рекомендации кадр не обязателен: «крышка открывается туго» не снять.
    if (!isAdvice() && !readyPhotos().length) return uploading() ? "walk.sheet.need_upload" : "walk.sheet.need_photo";
    if (uploading()) return "walk.sheet.need_upload";
    if (!f.zone) return "walk.sheet.need_zone";
    if (!f.code) return "walk.sheet.need_item";
    if (isAdvice()) return f.text.trim() ? null : "walk.sheet.need_advice";
    if (!taken() && !f.level) return "walk.sheet.need_level";
    return null;
  }

  function dirty() {
    if (!f.n) return !!(f.photos.length || f.code || f.text || f.comment || f.words);
    var o = f.original;
    return f.text !== o.text || f.comment !== o.comment || f.level !== o.level ||
      f.zone !== o.zone || f.code !== o.code || f.repeat !== o.repeat ||
      f.photos.some(function (p) { return p.fresh; }) || f.removed.length > 0;
  }

  function saveDraft() {
    if (f.n) return;
    W.local.set(draftKey(), {
      mode: f.mode, zone: f.zone, code: f.code, level: f.level, text: f.text,
      comment: f.comment, repeat: f.repeat, words: f.words,
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
    files.forEach(function (file) {
      var p = { id: ++seq, state: "uploading", fresh: true, own: true, url: URL.createObjectURL(file) };
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
      return W.photo.upload(b);
    }).then(function (ref) {
      if (!f || f.photos.indexOf(p) === -1) return;
      p.ref = ref;
      p.state = "done";
      W.photo.remember(ref, p.url);
      changed();
      redraw("photos", "item", "footer");
    }, function (err) {
      if (!f || f.photos.indexOf(p) === -1) return;
      p.state = "failed";
      p.error = err && err.message;
      p.file = file;
      redraw("photos", "item", "footer");
    });
  }

  function removePhoto(p) {
    var left = f.photos.filter(function (x) { return x !== p; });
    if (f.n && !isAdvice() && !left.some(function (x) { return x.state === "done"; })) {
      W.toast(tx("walk.photo.last"), "warn");
      return;
    }
    if (!p.fresh && p.ref) f.removed.push(p.ref);
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

  function zoneMenu() {
    W.menu.open({
      title: tx("walk.sheet.zone"),
      options: W.state.data.zones.filter(function (z) { return !z.equipment; }).map(function (z) {
        return { label: z.title, value: z.code, on: z.code === f.zone };
      }),
      onPick: function (code) {
        f.zone = code;
        changed();
        redraw.apply(null, ORDER.concat(["footer"]));
      },
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
      list: function (q) {
        return choices(q).map(function (i) {
          return { code: i.code, label: i.q, value: i.code, on: i.code === f.code, badge: previousHere(i.code) ? tx("walk.sheet.was_here") : null };
        });
      },
      onPick: function (code) { pick(code, null); },
    });
  }

  /**
   * Выбрать пункт — предложенный системой (`cand`) или вручную.
   * Класс и формулировку предложения форма берёт как черновик: поправить их
   * можно ниже, а записывается всё только по «Сохранить».
   */
  function pick(code, cand) {
    var i = item(code);
    if (!i) return;
    f.code = code;
    f.picked = cand ? cand : null;
    if (cand && cand.zone && zoneOf(cand.zone) && !zoneOf(cand.zone).equipment) f.zone = cand.zone;
    if (i.measure) f.level = "D0";
    else if (isAdvice() || i.note) f.level = ADVICE_LEVEL;
    else if (cand && i.levels.indexOf(cand.level) !== -1) f.level = cand.level;
    else if (i.levels.length === 1) f.level = i.levels[0];
    else if (i.levels.indexOf(f.level) === -1) f.level = null;
    var before = previousHere(code);
    if (before && !isAdvice() && !f.level && i.levels.indexOf(before.level) !== -1) f.level = before.level;
    if (cand && cand.wording && (!f.text.trim() || f.textAuto)) { f.text = cand.wording; f.textAuto = true; }
    W.haptic();
    changed();
    redraw.apply(null, ORDER.concat(["footer"]));
  }

  /* ── система ищет пункт (D330) ─────────────────────────────────────── */

  function find() {
    if (findBlocker() || f.finding) return;
    f.finding = true;
    f.findError = null;
    redraw("item", "footer");
    var asked = { words: f.words.trim(), photos: readyPhotos().map(function (p) { return p.ref; }) };
    W.post(W.urls.suggest, { zone: f.zone, words: asked.words, photos: asked.photos }).then(function (res) {
      if (!f) return;
      if (!res.ok) throw new Error((res.body && res.body.message) || tx("walk.error"));
      f.finding = false;
      f.found = (res.body && res.body.candidates) || [];
      f.question = (res.body && res.body.question) || "";
      f.via = (res.body && res.body.via) || "model";
      f.asked = JSON.stringify(asked);
      if (f.found.length) pick(f.found[0].code, f.found[0]);
      else { redraw("item", "footer"); }
    }).catch(function (err) {
      if (!f) return;
      f.finding = false;
      f.findError = err && err.message && err.message !== "Failed to fetch" ? err.message : tx("walk.err.network");
      redraw("item", "footer");
    });
  }

  /** Слова или кадры поменялись после поиска — предложения могли устареть. */
  function stale() {
    if (!f.found) return false;
    return f.asked !== JSON.stringify({ words: f.words.trim(), photos: readyPhotos().map(function (p) { return p.ref; }) });
  }

  function proposal(cand) {
    var i = item(cand.code) || { q: cand.code };
    var on = f.code === cand.code && (!f.picked || f.picked === cand);
    var b = W.button("walk-found__card" + (on ? " is-on" : ""), null, function () { pick(cand.code, cand); });
    b.setAttribute("aria-pressed", on ? "true" : "false");
    var top = el("span", "walk-found__top");
    top.appendChild(el("span", "walk-option__code", cand.code));
    if (cand.level && cand.level !== ADVICE_LEVEL) top.appendChild(W.level(cand.level));
    var z = zoneOf(cand.zone);
    if (z && cand.zone !== f.zone) top.appendChild(el("span", "walk-found__zone", z.title));
    b.appendChild(top);
    b.appendChild(el("span", "walk-found__q", i.q));
    return b;
  }

  /* ── секции ───────────────────────────────────────────────────────── */

  var draw = {
    context: function () {
      var row = el("div", "walk-ctx");
      if (!f.n && !isMeasure()) {
        var kind = KINDS.filter(function (pair) { return pair[0] === f.mode; })[0];
        row.appendChild(W.button("walk-ctx__pill", tx(kind[1]), kindMenu));
      }
      var z = zoneOf(f.zone);
      var zb = W.button("walk-ctx__pill walk-ctx__pill--zone" + (z ? "" : " is-empty"),
        (z ? z.title : tx("walk.sheet.pick_zone")), zoneMenu);
      zb.setAttribute("aria-label", tx("walk.sheet.zone") + ": " + (z ? z.title : tx("walk.sheet.pick_zone")));
      row.appendChild(zb);
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
      return box;
    },

    item: function () {
      if (recognizing()) return found();
      var box = section(isMeasure() ? tx("walk.sheet.item_measure") : isAdvice() ? tx("walk.sheet.item_advice") : tx("walk.sheet.item"));
      var chosen = item(f.code);
      if (!chosen) {
        box.appendChild(W.button("walk-btn walk-btn--pick", tx("walk.sheet.pick_item"), itemMenu));
        return box;
      }
      var card = el("div", "walk-choice");
      var line = el("div", "walk-choice__line");
      if (!chosen.note) line.appendChild(el("span", "walk-choice__code", chosen.code));
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

    level: function () {
      var it = item(f.code);
      if (!it || isMeasure() || isAdvice() || taken()) return null;
      var box = section(tx("walk.sheet.level"));
      if (it.levels.length === 1) {
        box.appendChild(el("p", "walk-form__hint", tx("walk.sheet.level_only", { level: it.levels[0] })));
        return box;
      }
      var seg = el("div", "walk-seg");
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
          if (a) a.focus();
        }));
        return box;
      }
      box.appendChild(el("p", "walk-form__hint", tx("walk.sheet.comment_hint")));
      var area = el("textarea", "walk-area walk-area--comment");
      area.rows = 3;
      area.maxLength = 1000;
      area.value = f.comment;
      area.addEventListener("input", function () { f.comment = area.value; changed(); });
      box.appendChild(area);
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
      if (recognizing() && !f.code) {
        var blocked = findBlocker();
        var go = W.button("walk-mark walk-mark--find", f.finding ? tx("walk.sheet.finding_short") : tx("walk.sheet.find"), find);
        go.disabled = !!blocked || !!f.finding;
        box.appendChild(go);
        if (blocked) box.appendChild(el("p", "walk-sheet__why", tx(blocked)));
        return box;
      }
      var why = blocker();
      var label = f.saving ? tx("walk.sheet.saving") : taken() ? tx("walk.sheet.add_photos") : tx("walk.sheet.save");
      var save = W.button("walk-mark", label, save_);
      save.disabled = !!why || f.saving;
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
      return box;
    }
    if (f.findError) box.appendChild(el("p", "walk-form__error", f.findError));
    var list = el("div", "walk-found");
    (f.found || []).forEach(function (cand) { list.appendChild(proposal(cand)); });
    var manual = item(f.code);
    var fromList = (f.found || []).some(function (c) { return c.code === f.code; });
    if (manual && !fromList) list.appendChild(proposal({ code: f.code, level: f.level, zone: f.zone }));
    if (list.childNodes.length) box.appendChild(list);
    if (f.found && !f.found.length) box.appendChild(el("p", "walk-form__note", tx("walk.sheet.found_none")));
    if (f.question) box.appendChild(el("p", "walk-form__note walk-form__note--info", f.question));
    if (stale()) {
      var again = el("p", "walk-form__note walk-form__note--info");
      again.appendChild(document.createTextNode(tx("walk.sheet.found_stale") + " "));
      again.appendChild(W.button("walk-link", tx("walk.sheet.find_again"), find));
      box.appendChild(again);
    }
    if (!f.found && !f.code) box.appendChild(el("p", "walk-form__hint", tx("walk.sheet.find_hint")));
    box.appendChild(W.button("walk-link", tx("walk.sheet.pick_manual"), itemMenu));
    var t = taken();
    if (t) box.appendChild(el("p", "walk-form__note walk-form__note--info", tx("walk.sheet.taken", { n: t.n })));
    return box;
  }

  var ORDER = ["context", "photos", "words", "item", "level", "text", "comment", "repeat", "danger"];

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

  function ops() {
    var refs = readyPhotos().filter(function (p) { return p.fresh; }).map(function (p) { return p.ref; });
    var t = taken();
    if (t) return refs.map(function (ref) { return { op: "attach", n: t.n, ref: ref }; });
    if (!f.n) {
      return [{
        op: "add", zone: f.zone, code: f.code, level: isAdvice() ? ADVICE_LEVEL : f.level, text: f.text.trim(),
        comment: f.comment.trim(), repeat: !!f.repeat && repeatOffered(),
        photos: readyPhotos().map(function (p) { return p.ref; }),
        words: f.words.trim(), suggested: suggested(),
      }];
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
    var list = refs.map(function (ref) { return { op: "attach", n: f.n, ref: ref }; });
    if (any) list.unshift(edit);
    // Снимать — после того, как новые кадры легли: запись ни на миг без фото.
    return list.concat(f.removed.map(function (ref) { return { op: "detach", n: f.n, ref: ref }; }));
  }

  function save_() {
    if (blocker()) return;
    var list = ops();
    if (!list.length) { close(true); return; }
    submit(list);
  }

  function submit(list) {
    f.saving = true;
    f.error = null;
    redraw("footer");
    var last = null;
    var chain = list.reduce(function (p, body) {
      return p.then(function () {
        return W.post(W.urls.finding, body).then(function (res) {
          if (!res.ok) throw new Error((res.body && res.body.message) || tx("walk.error"));
          last = res.body;
        });
      });
    }, Promise.resolve());
    chain.then(function () {
      if (!f.n) W.local.drop(draftKey());
      W.haptic("success");
      W.toast(tx("walk.sheet.saved"), "ok");
      close(true);
      if (last) W.apply(last);
    }, function (err) {
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
    if (W.menu) W.menu.close();
    if (node) node.remove();
    node = null;
    document.documentElement.classList.remove("has-sheet");
    if (W.tg && W.supports("6.1")) {
      W.tg.BackButton.offClick(onBack);
      W.tg.BackButton.hide();
    }
    if (W.tg && W.supports("6.2")) W.tg.disableClosingConfirmation();
  }

  function onBack() { close(false); }

  /**
   * Открыть форму.
   *   { mode: "violation" | "advice" | "measure", zone, code, level, repeat } — новая запись;
   *   { record: <запись из данных>, zone } — правка.
   */
  function open(opts) {
    if (f) close(true);
    var rec = opts.record;
    f = {
      mode: opts.mode || "violation",
      n: rec ? rec.n : null,
      zone: opts.zone || null,
      code: opts.code || null,
      level: opts.level || null,
      text: "",
      comment: "",
      repeat: !!opts.repeat,
      photos: [],
      removed: [],
      words: "",
      found: null,
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
      f.original = { code: rec.code, level: rec.level, zone: opts.zone, text: rec.text, comment: rec.comment || "", repeat: !!rec.repeat };
    } else {
      var draft = W.local.get(draftKey());
      if (draft && !opts.code && draft.mode === f.mode && (draft.code || draft.words || (draft.photos || []).length)) {
        f.zone = draft.zone || f.zone;
        f.code = draft.code;
        f.level = draft.level;
        f.text = draft.text || "";
        f.comment = draft.comment || "";
        f.words = draft.words || "";
        f.commentOpen = !!draft.comment;
        f.repeat = !!draft.repeat;
        f.photos = (draft.photos || []).map(function (ref) { return { id: ++seq, ref: ref, own: true, state: "done", fresh: true }; });
        f.restored = true;
      }
    }
    build();
  }

  function build() {
    node = el("div", "walk-sheet");
    node.setAttribute("role", "dialog");
    node.setAttribute("aria-modal", "true");
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
    document.body.appendChild(node);
    document.documentElement.classList.add("has-sheet");
    if (W.tg && W.supports("6.1")) {
      W.tg.BackButton.onClick(onBack);
      W.tg.BackButton.show();
    }
    changed();
  }

  W.sheet = { open: open, close: close, isOpen: function () { return !!f; } };
})();
