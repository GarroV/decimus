// Каркас «слева список, справа выбранное» (`_split_page.html`). Страница
// работает и без этого файла: выбор — ссылкой, фильтры — кнопкой «Показать»,
// подтверждение — раскрывающимся блоком. Скрипт добавляет удобства:
//   * Esc — назад к списку (на телефоне это «Назад» в карточке);
//   * фильтры применяются сразу при выборе, кнопка «Показать» прячется;
//   * «Скопировать» у одноразового пароля;
//   * в форме «Новый человек» роли сужаются под выбранное пространство.
(function () {
  "use strict";

  function typing(el) {
    return el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT");
  }

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape" || typing(document.activeElement)) return;
    var split = document.querySelector(".split--open");
    var back = document.querySelector("[data-split-back]");
    if (split && back) window.location.href = back.href;
  });

  document.querySelectorAll("form[data-autosubmit]").forEach(function (form) {
    var button = form.querySelector("[data-autosubmit-button]");
    if (button) button.hidden = true;
    form.addEventListener("change", function (e) {
      if (e.target && e.target.type !== "search") form.submit();
    });
  });

  document.querySelectorAll("[data-copy]").forEach(function (button) {
    var source = document.querySelector(button.dataset.copy);
    if (!source || !navigator.clipboard) return;
    button.hidden = false;
    button.addEventListener("click", function () {
      navigator.clipboard.writeText(source.textContent.trim()).then(function () {
        button.textContent = button.dataset.copied;
      });
    });
  });

  document.querySelectorAll("form[data-role-by-space]").forEach(function (form) {
    var select = form.querySelector("[data-space-select]");
    if (!select) return;
    function narrow() {
      var first = null;
      form.querySelectorAll(".srole[data-spaces]").forEach(function (label) {
        var fits = (" " + label.dataset.spaces).indexOf(" " + select.value + " ") !== -1;
        label.hidden = !fits;
        var radio = label.querySelector("input");
        radio.disabled = !fits;
        if (fits && !first) first = radio;
        if (!fits) radio.checked = false;
      });
      if (first && !form.querySelector(".srole input:checked")) first.checked = true;
    }
    select.addEventListener("change", narrow);
    narrow();
  });
})();
