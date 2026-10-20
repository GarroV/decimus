// Правка прямо в записях на вычитке и «+ Добавить нарушение» (D535).
//
// Разметка — `_card_body.html` (макросы `edit_form`, `composer`, `item_picker`,
// `photo_editor`). Скрипт ничего не решает за сервер: он раскрывает формы, сужает
// выбор пункта/класса/зоны по данным версии чек-листа и просит у системы
// предложения. Запись создаётся и меняется только отправкой формы; допустимость
// пункта, класса и зоны, оценку и права проверяет сервер.
//
// Работает на обеих поверхностях карточки: в панели реестра (форму отправляет
// фоном `split.js`) и на странице `/inspections/<id>` (обычная отправка). Все
// обработчики — на `document`, поэтому переживают замену карточки после действия.
(function () {
  "use strict";

  var dataCache = new WeakMap();

  // ── Данные версии: пункты, классы, зоны, тексты ────────────────────────────
  function sectionOf(el) {
    return el.closest("[data-proofread]");
  }

  function dataOf(el) {
    var section = sectionOf(el);
    if (!section) return null;
    if (dataCache.has(section)) return dataCache.get(section);
    var parsed = null;
    try {
      parsed = section.dataset.proofreadData ? JSON.parse(section.dataset.proofreadData) : null;
    } catch (err) {
      parsed = null;
    }
    if (parsed) {
      parsed.byCode = {};
      parsed.items.forEach(function (item) {
        parsed.byCode[item.c] = item;
      });
    }
    dataCache.set(section, parsed);
    return parsed;
  }

  function fill(template, values) {
    return template.replace(/\{(\w+)\}/g, function (m, key) {
      return key in values ? values[key] : m;
    });
  }

  // ── Раскрыть / свернуть форму ──────────────────────────────────────────────
  function toggleForm(form, button, on) {
    form.hidden = !on;
    if (button) button.setAttribute("aria-expanded", on ? "true" : "false");
    if (on) {
      initPicker(form);
      refreshAdd(form);
      var first = form.querySelector("textarea");
      if (first) first.focus({ preventScroll: false });
    }
  }

  function buttonFor(form) {
    return document.querySelector('[aria-controls="' + form.id + '"]');
  }

  function resetForm(form) {
    form.reset();
    // Скрытое поле `form.reset()` не возвращает: у него значение и есть атрибут.
    var code = form.querySelector("[data-ipick-value]");
    if (code) code.value = code.dataset.orig || "";
    clearNewShots(form);
    form.querySelectorAll(".pshot.is-removed").forEach(function (shot) {
      shot.classList.remove("is-removed");
    });
    var list = form.querySelector("[data-suggest-list]");
    if (list) {
      list.hidden = true;
      list.textContent = "";
    }
    var status = form.querySelector("[data-suggest-status]");
    if (status) status.textContent = "";
    closePicker(form.querySelector("[data-ipick]"));
    initPicker(form);
    refreshAdd(form);
  }

  document.addEventListener("click", function (e) {
    var edit = e.target.closest("[data-proofread-edit]");
    if (edit) {
      var form = document.getElementById(edit.getAttribute("aria-controls"));
      if (form) toggleForm(form, edit, form.hidden);
      return;
    }
    var add = e.target.closest("[data-proofread-add]");
    if (add) {
      var composer = document.getElementById(add.getAttribute("aria-controls"));
      if (composer) toggleForm(composer, add, composer.hidden);
      return;
    }
    var cancel = e.target.closest("[data-proofread-cancel]");
    if (cancel) {
      var closing = cancel.closest("form");
      resetForm(closing);
      toggleForm(closing, buttonFor(closing), false);
    }
  });

  // ── Выбор пункта ───────────────────────────────────────────────────────────
  function itemTitle(item) {
    // Поиск идёт и по коду (его знают привыкшие), но на экране код не показывается.
    return item.c + " " + item.n + " — " + item.q;
  }

  function showChosen(picker, item) {
    var out = picker.querySelector("[data-ipick-chosen]");
    var open = picker.querySelector("[data-ipick-open]");
    open.textContent = item ? open.dataset.labelChange : open.dataset.labelFind;
    out.textContent = "";
    if (!item) {
      out.textContent = out.dataset.empty;
      out.classList.add("is-empty");
      return;
    }
    out.classList.remove("is-empty");
    var code = document.createElement("span");
    code.className = "ipick__code";
    code.textContent = item.n;
    var title = document.createElement("span");
    title.textContent = item.q;
    out.appendChild(code);
    out.appendChild(title);
  }

  function initPicker(form) {
    var picker = form.querySelector("[data-ipick]");
    var data = picker && dataOf(picker);
    if (!picker || !data) return;
    var code = picker.querySelector("[data-ipick-value]").value;
    showChosen(picker, data.byCode[code] || null);
    narrowByItem(form, data.byCode[code] || null, false);
    // Пункт не выбран (новое нарушение) — выбор сразу открыт: искать есть что.
    if (!code && form.dataset.proofreadForm === "add") openPicker(picker);
  }

  function renderList(picker, needle) {
    var data = dataOf(picker);
    var list = picker.querySelector("[data-ipick-list]");
    list.textContent = "";
    var words = needle.trim().toLowerCase().split(/\s+/).filter(Boolean);
    var shown = 0;
    data.items.forEach(function (item) {
      var hay = itemTitle(item).toLowerCase();
      if (!words.every(function (w) { return hay.indexOf(w) !== -1; })) return;
      shown += 1;
      var li = document.createElement("li");
      var btn = document.createElement("button");
      btn.type = "button";
      btn.setAttribute("role", "option");
      btn.className = "ipick__opt";
      btn.dataset.code = item.c;
      var c = document.createElement("span");
      c.className = "ipick__code";
      c.textContent = item.n;
      var q = document.createElement("span");
      q.textContent = item.q;
      btn.appendChild(c);
      btn.appendChild(q);
      li.appendChild(btn);
      list.appendChild(li);
    });
    if (!shown) {
      var empty = document.createElement("li");
      empty.className = "ipick__none";
      empty.textContent = data.nothing;
      list.appendChild(empty);
    }
  }

  function openPicker(picker) {
    picker.querySelector("[data-ipick-panel]").hidden = false;
    picker.querySelector("[data-ipick-open]").setAttribute("aria-expanded", "true");
    var search = picker.querySelector("[data-ipick-search]");
    search.value = "";
    renderList(picker, "");
  }

  function closePicker(picker) {
    if (!picker) return;
    picker.querySelector("[data-ipick-panel]").hidden = true;
    picker.querySelector("[data-ipick-open]").setAttribute("aria-expanded", "false");
  }

  function chooseItem(form, code) {
    var picker = form.querySelector("[data-ipick]");
    var data = dataOf(picker);
    var item = data.byCode[code] || null;
    picker.querySelector("[data-ipick-value]").value = item ? item.c : "";
    showChosen(picker, item);
    closePicker(picker);
    narrowByItem(form, item, true);
    refreshAdd(form);
  }

  // Классы, которых у пункта нет, гасятся; выбранный, ставший недопустимым, снимается.
  function narrowByItem(form, item, changed) {
    var radios = form.querySelectorAll("[data-lvls] input[type=radio]");
    radios.forEach(function (radio) {
      var allowed = !item || !item.l.length || item.l.indexOf(radio.value) !== -1;
      radio.disabled = !allowed;
      radio.closest("label").classList.toggle("is-off", !allowed);
      if (!allowed && radio.checked) radio.checked = false;
    });
    if (changed && item) {
      var anyChecked = form.querySelector("[data-lvls] input:checked");
      var open = Array.prototype.filter.call(radios, function (r) {
        return !r.disabled;
      });
      if (!anyChecked && open.length === 1) open[0].checked = true;
    }
    var zone = form.querySelector("select[name=zone]");
    if (zone && item) {
      Array.prototype.forEach.call(zone.options, function (o) {
        o.classList.toggle("is-own", item.z.indexOf(o.value) !== -1);
      });
    }
  }

  document.addEventListener("click", function (e) {
    var open = e.target.closest("[data-ipick-open]");
    if (open) {
      var picker = open.closest("[data-ipick]");
      if (picker.querySelector("[data-ipick-panel]").hidden) {
        openPicker(picker);
        picker.querySelector("[data-ipick-search]").focus();
      } else {
        closePicker(picker);
      }
      return;
    }
    var opt = e.target.closest(".ipick__opt");
    if (opt) chooseItem(opt.closest("form"), opt.dataset.code);
  });

  document.addEventListener("input", function (e) {
    var search = e.target.closest && e.target.closest("[data-ipick-search]");
    if (search) renderList(search.closest("[data-ipick]"), search.value);
    var form = e.target.closest && e.target.closest("form[data-proofread-form]");
    if (form) refreshAdd(form);
  });

  document.addEventListener("change", function (e) {
    var form = e.target.closest && e.target.closest("form[data-proofread-form]");
    if (form) refreshAdd(form);
  });

  // «Добавить» не нажать, пока нет слов, пункта и класса: сервер всё равно не
  // примет, а так видно, чего не хватает (подсказка на кнопке).
  function refreshAdd(form) {
    if (form.dataset.proofreadForm !== "add") return;
    var submit = form.querySelector("button[type=submit]");
    var ready =
      form.querySelector("[data-ipick-value]").value &&
      form.querySelector("[data-lvls] input:checked") &&
      form.querySelector("textarea[name=text]").value.trim();
    submit.disabled = !ready;
    if (ready) submit.removeAttribute("title");
    else submit.title = submit.dataset.needItem || "";
  }

  // ── Кадры: выбор, перетаскивание, снятие до сохранения ─────────────────────
  var staged = new WeakMap(); // input -> DataTransfer: накопленные новые кадры

  function stagedOf(input) {
    if (!staged.has(input)) staged.set(input, new DataTransfer());
    return staged.get(input);
  }

  function existingCount(form) {
    return form.querySelectorAll(".pshot:not(.is-removed):not(.pshot--new)").length;
  }

  function crossIcon() {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("width", "12");
    svg.setAttribute("height", "12");
    svg.setAttribute("aria-hidden", "true");
    var path = document.createElementNS(ns, "path");
    path.setAttribute("d", "M3 3l10 10M13 3L3 13");
    path.setAttribute("stroke", "currentColor");
    path.setAttribute("stroke-width", "1.8");
    path.setAttribute("fill", "none");
    path.setAttribute("stroke-linecap", "round");
    svg.appendChild(path);
    return svg;
  }

  // Миниатюра нового кадра рисуется в <canvas>: политика источников админки не
  // пускает картинки из blob:/data:, а canvas читает файл напрямую.
  var THUMB = 72;
  function thumbnail(file) {
    var canvas = document.createElement("canvas");
    canvas.className = "pshot__img";
    canvas.width = THUMB * 2;
    canvas.height = THUMB * 2;
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", file.name);
    if (window.createImageBitmap) {
      window
        .createImageBitmap(file)
        .then(function (bitmap) {
          var side = Math.min(bitmap.width, bitmap.height);
          var ctx = canvas.getContext("2d");
          ctx.drawImage(
            bitmap,
            (bitmap.width - side) / 2,
            (bitmap.height - side) / 2,
            side,
            side,
            0,
            0,
            canvas.width,
            canvas.height
          );
          if (bitmap.close) bitmap.close();
        })
        .catch(function () {});
    }
    return canvas;
  }

  function renderNewShots(form) {
    var input = form.querySelector("[data-pshots-input]");
    var box = form.querySelector("[data-pshots-new]");
    box.textContent = "";
    var files = stagedOf(input).files;
    Array.prototype.forEach.call(files, function (file, index) {
      var shot = document.createElement("span");
      shot.className = "pshot pshot--new";
      var thumb = thumbnail(file);
      var x = document.createElement("button");
      x.type = "button";
      x.className = "pshot__x";
      x.dataset.dropIndex = String(index);
      x.title = form.querySelector(".pshot__x[title]")
        ? form.querySelector(".pshot__x[title]").title
        : "×";
      x.appendChild(crossIcon());
      shot.appendChild(thumb);
      shot.appendChild(x);
      box.appendChild(shot);
    });
    input.files = stagedOf(input).files;
  }

  function addFiles(form, fileList) {
    var data = dataOf(form);
    var input = form.querySelector("[data-pshots-input]");
    var dt = stagedOf(input);
    var cap = (data && data.max_photos) || 10;
    Array.prototype.forEach.call(fileList, function (file) {
      if (file.type && file.type.indexOf("image/") !== 0) return;
      if (existingCount(form) + dt.items.length >= cap) return;
      dt.items.add(file);
    });
    renderNewShots(form);
  }

  function clearNewShots(form) {
    var input = form.querySelector("[data-pshots-input]");
    if (!input) return;
    staged.set(input, new DataTransfer());
    renderNewShots(form);
  }

  document.addEventListener("change", function (e) {
    var input = e.target.closest && e.target.closest("[data-pshots-input]");
    if (input) {
      // Выбор в диалоге заменил бы список — копим, а не заменяем.
      var picked = Array.prototype.slice.call(input.files);
      input.value = "";
      addFiles(input.closest("form"), picked);
      return;
    }
    var removal = e.target.closest && e.target.closest("[data-pshot-remove]");
    if (removal) {
      var shot = removal.closest(".pshot");
      var label = removal.closest(".pshot__x");
      shot.classList.toggle("is-removed", removal.checked);
      var swap = label.dataset.removeLabel;
      label.dataset.removeLabel = label.title;
      label.title = swap;
    }
  });

  document.addEventListener("click", function (e) {
    var x = e.target.closest(".pshot--new .pshot__x");
    if (!x) return;
    var form = x.closest("form");
    var input = form.querySelector("[data-pshots-input]");
    var kept = new DataTransfer();
    Array.prototype.forEach.call(stagedOf(input).files, function (file, index) {
      if (String(index) !== x.dataset.dropIndex) kept.items.add(file);
    });
    staged.set(input, kept);
    renderNewShots(form);
  });

  ["dragenter", "dragover"].forEach(function (name) {
    document.addEventListener(name, function (e) {
      var zone = e.target.closest && e.target.closest("[data-drop]");
      if (!zone) return;
      e.preventDefault();
      zone.classList.add("is-over");
    });
  });
  ["dragleave", "drop"].forEach(function (name) {
    document.addEventListener(name, function (e) {
      var zone = e.target.closest && e.target.closest("[data-drop]");
      if (!zone) return;
      zone.classList.remove("is-over");
      if (name !== "drop") return;
      e.preventDefault();
      if (e.dataTransfer && e.dataTransfer.files.length) addFiles(zone.closest("form"), e.dataTransfer.files);
    });
  });

  // ── Подбор пункта системой (тот же поиск, что у бота и мини-аппа) ──────────
  function pct(value) {
    return String(Math.round(value * 100));
  }

  function tag(text, extra) {
    var span = document.createElement("span");
    span.className = "tag tag--micro " + (extra || "");
    span.textContent = text;
    return span;
  }

  function renderSuggestions(form, answer) {
    var data = dataOf(form);
    var list = form.querySelector("[data-suggest-list]");
    list.textContent = "";
    list.hidden = false;
    // Предложения есть — длинный список пунктов не нужен, он по кнопке «Найти пункт».
    if (answer.candidates.length) closePicker(form.querySelector("[data-ipick]"));
    var head = document.createElement("div");
    head.className = "suggest__title";
    head.textContent = data.title;
    list.appendChild(head);
    if (answer.question) {
      var q = document.createElement("p");
      q.className = "field-note";
      q.textContent = fill(data.question, { question: answer.question });
      list.appendChild(q);
    }
    if (!answer.candidates.length) {
      var none = document.createElement("p");
      none.className = "field-note";
      none.textContent = data.none;
      list.appendChild(none);
      return;
    }
    answer.candidates.forEach(function (card) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "suggest__opt";
      btn.setAttribute("aria-pressed", "false");
      btn.dataset.code = card.code;
      btn.dataset.level = card.level;
      btn.dataset.zone = card.zone;
      btn.dataset.wording = card.wording || "";
      var main = document.createElement("span");
      main.className = "suggest__main";
      var code = document.createElement("span");
      code.className = "ipick__code";
      code.textContent = card.label;
      var title = document.createElement("span");
      title.textContent = card.title;
      main.appendChild(code);
      main.appendChild(title);
      var meta = document.createElement("span");
      meta.className = "suggest__meta";
      if (card.level) meta.appendChild(tag(card.level, "tag--neutral"));
      if (card.zone_name) {
        var zone = document.createElement("span");
        zone.textContent = card.zone_name;
        meta.appendChild(zone);
      }
      if (card.confidence && card.confidence < 1) {
        var sure = document.createElement("span");
        sure.textContent = fill(data.sure, { pct: pct(card.confidence) });
        meta.appendChild(sure);
      }
      btn.appendChild(main);
      btn.appendChild(meta);
      list.appendChild(btn);
    });
  }

  function applySuggestion(form, btn) {
    form.querySelectorAll(".suggest__opt").forEach(function (other) {
      other.setAttribute("aria-pressed", other === btn ? "true" : "false");
    });
    chooseItem(form, btn.dataset.code);
    var level = form.querySelector('[data-lvls] input[value="' + btn.dataset.level + '"]');
    if (level && !level.disabled) level.checked = true;
    var zone = form.querySelector("select[name=zone]");
    if (zone && btn.dataset.zone) zone.value = btn.dataset.zone;
    var text = form.querySelector("textarea[name=text]");
    // Слова человека не затираются: формулировка системы нужна, когда он писал только фото.
    if (text && !text.value.trim() && btn.dataset.wording) text.value = btn.dataset.wording;
    refreshAdd(form);
  }

  document.addEventListener("click", function (e) {
    var opt = e.target.closest(".suggest__opt");
    if (opt) {
      applySuggestion(opt.closest("form"), opt);
      return;
    }
    var ask = e.target.closest("[data-suggest]");
    if (!ask) return;
    var form = ask.closest("form");
    var data = dataOf(form);
    var status = form.querySelector("[data-suggest-status]");
    var label = ask.querySelector("span");
    var body = new FormData();
    body.append("text", form.querySelector("textarea[name=text]").value);
    Array.prototype.forEach.call(stagedOf(form.querySelector("[data-pshots-input]")).files, function (file) {
      body.append("photo", file);
    });
    var idle = label.textContent;
    ask.disabled = true;
    label.textContent = data.busy;
    status.textContent = "";
    fetch(form.dataset.suggestUrl, { method: "POST", body: body, credentials: "same-origin" })
      .then(function (r) {
        return r.json().then(function (json) {
          return { ok: r.ok, json: json };
        });
      })
      .then(function (res) {
        if (!res.ok) {
          status.textContent = (res.json && res.json.message) || data.net;
          return;
        }
        renderSuggestions(form, res.json);
      })
      .catch(function () {
        status.textContent = data.net;
      })
      .then(function () {
        ask.disabled = false;
        label.textContent = idle;
      });
  });

  // ── Отправка и возврат формы после отказа ──────────────────────────────────
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form.matches || !form.matches("form[data-proofread-form]")) return;
    var submit = form.querySelector("button[type=submit]");
    if (submit && submit.dataset.saving) submit.textContent = submit.dataset.saving;
  });

  // Что вписано в форму — запоминается перед отправкой (`split.js`), чтобы при отказе
  // сервера форма раскрылась снова со словами человека. Кадры не возвращаются:
  // браузер не даёт подставить файлы обратно.
  window.Proofread = {
    snapshot: function (form) {
      if (!form.matches || !form.matches("form[data-proofread-form]")) return null;
      var pick = function (name) {
        var field = form.elements[name];
        return field ? field.value : null;
      };
      var level = form.querySelector("[data-lvls] input:checked");
      return {
        id: form.id,
        text: pick("text"),
        code: pick("code"),
        level: level ? level.value : "",
        zone: pick("zone"),
        reading: pick("reading_c"),
      };
    },
    restore: function (root, state) {
      var form = root.querySelector("#" + state.id);
      if (!form) return;
      toggleForm(form, buttonFor(form), true);
      var set = function (name, value) {
        if (value !== null && form.elements[name]) form.elements[name].value = value;
      };
      set("text", state.text);
      set("zone", state.zone);
      set("reading_c", state.reading);
      if (state.code) chooseItem(form, state.code);
      var level = form.querySelector('[data-lvls] input[value="' + state.level + '"]');
      if (level && !level.disabled) level.checked = true;
      refreshAdd(form);
    },
  };
})();
