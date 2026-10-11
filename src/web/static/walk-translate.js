/* Мини-апп обхода: перевод свободного текста на язык отчёта (D394, #542).
 *
 * Под полем со свободным текстом (что видно, рекомендация партнёру, общая
 * заметка, сведение о визите) — кнопка «Перевести на <язык отчёта>». Видна,
 * только пока в поле есть текст. По нажатию текст уходит в `/tg/walk/translate`,
 * перевод ложится ПРЯМО В ПОЛЕ — аудитор видит его до сохранения и правит, —
 * а прежний текст запоминается: ссылка «Вернуть как было» возвращает его.
 * Сама запись остаётся за обычной кнопкой «Сохранить»: модель предлагает,
 * фиксирует человек.
 *
 * Отказ (модель недоступна, слишком длинно) — строкой под полем, поле не
 * меняется. Строки — из ответа сервера, как везде в мини-аппе.
 */
(function () {
  "use strict";

  var W = (window.DecimusWalk = window.DecimusWalk || {});

  function langName(code) {
    var key = "walk.translate.lang." + code;
    var name = W.tx(key);
    return name === key ? String(code).toUpperCase() : name;
  }

  /**
   * Полоса перевода под полем `area`. Возвращает узел, который кладут сразу
   * после поля, или null, когда переводить некуда (нет языка отчёта, поле
   * закрыто для правки).
   *
   * Поле меняется как при вводе: после подстановки перевода на нём вызывается
   * событие `input`, чтобы форма узнала о новом тексте тем же путём.
   */
  W.translateBar = function (area) {
    var lang = W.state.data && W.state.data.report_lang;
    if (!lang || area.disabled) return null;

    var el = W.el;
    var bar = el("div", "walk-translate");
    var row = el("div", "walk-translate__row");
    var go = W.button("walk-link walk-translate__go", W.tx("walk.translate.btn", { lang: langName(lang) }));
    var undo = W.button("walk-link walk-link--quiet walk-translate__undo", W.tx("walk.translate.undo"));
    var note = el("p", "walk-form__hint walk-translate__note", W.tx("walk.translate.hint"));
    var error = el("p", "walk-form__error walk-translate__error");
    error.setAttribute("role", "alert");
    undo.hidden = true;
    note.hidden = true;
    error.hidden = true;
    row.appendChild(go);
    row.appendChild(undo);
    bar.appendChild(row);
    bar.appendChild(note);
    bar.appendChild(error);

    var original = null;
    var busy = false;

    function sync() { go.hidden = !area.value.trim(); }

    function setValue(value) {
      area.value = value;
      area.dispatchEvent(new Event("input", { bubbles: true }));
      sync();
    }

    function fail(message) {
      error.textContent = message;
      error.hidden = false;
      W.haptic("error");
    }

    function ask() {
      if (busy) return;
      var sent = area.value;
      if (!sent.trim()) return;
      busy = true;
      error.hidden = true;
      go.disabled = true;
      go.textContent = W.tx("walk.translate.busy");
      area.readOnly = true;
      W.post(W.urls.translate, { text: sent }).then(function (res) {
        if (!res.ok || !res.body || typeof res.body.text !== "string") {
          throw new Error((res.body && res.body.message) || W.tx("walk.error"));
        }
        // «Как было» запоминается один раз: повторный перевод не затирает
        // исходник текстом, который уже был переводом.
        if (original === null) original = sent;
        setValue(res.body.text);
        undo.hidden = false;
        note.hidden = false;
        W.haptic("success");
      }).catch(function (e) {
        fail(e && e.message ? e.message : W.tx("walk.error"));
      }).then(function () {
        busy = false;
        area.readOnly = false;
        go.disabled = false;
        go.textContent = W.tx("walk.translate.btn", { lang: langName(lang) });
        sync();
      });
    }

    go.addEventListener("click", ask);
    undo.addEventListener("click", function () {
      if (original === null) return;
      setValue(original);
      original = null;
      undo.hidden = true;
      note.hidden = true;
      error.hidden = true;
    });
    area.addEventListener("input", sync);
    sync();
    return bar;
  };
})();
