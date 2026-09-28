// Оболочка админки: ⌘K в поиск левой панели и переключатель темы (эталон —
// Swarm Brain). Страница работает и без этого файла: поиск остаётся обычной
// формой, тема — системной.
(function () {
  "use strict";
  var STORE = "decimus-theme";

  document.addEventListener("keydown", function (e) {
    var field = document.querySelector("[data-hotkey='k']");
    if (!field) return;
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      field.focus();
      field.select();
    } else if (e.key === "Escape" && document.activeElement === field) {
      field.value = "";
      field.blur();
    }
  });

  function stored() {
    try { return localStorage.getItem(STORE); } catch (e) { return null; }
  }

  function mark(choice) {
    document.querySelectorAll("[data-theme-value]").forEach(function (b) {
      b.setAttribute("aria-checked", String(b.dataset.themeValue === choice));
    });
  }

  function apply(choice) {
    try {
      if (choice === "system") localStorage.removeItem(STORE);
      else localStorage.setItem(STORE, choice);
    } catch (e) { /* приватный режим: выбор живёт до перезагрузки */ }
    var dark = choice === "dark" || (choice === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    mark(choice);
  }

  document.addEventListener("DOMContentLoaded", function () {
    var now = stored();
    mark(now === "light" || now === "dark" ? now : "system");
    document.querySelectorAll("[data-theme-value]").forEach(function (b) {
      b.addEventListener("click", function () { apply(b.dataset.themeValue); });
    });
  });
})();
