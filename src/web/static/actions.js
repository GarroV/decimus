// «Действия»: поле загрузки файла в панели (`.supload`, decimus-actions.css).
// Без скрипта поле работает само — настоящий `<input type=file>` лежит поверх
// зоны. Скрипт добавляет только подсказки: имя выбранного файла и подсветку при
// перетаскивании. Слушатели повешены на документ: панель подменяется целиком
// после каждого действия (`split.js`), и привязка к узлам пропала бы вместе с ним.
(function () {
  "use strict";

  function zoneOf(node) {
    return node && node.closest ? node.closest(".supload") : null;
  }

  // Панель правки строки плана (`.prowpanel`, `_plan_rows.html`): без скрипта её
  // открывает якорь (:target), со скриптом — класс `is-open` без перехода по адресу.
  // Esc закрывает сначала её, а не панель запроса под ней (слушатель в фазе захвата).
  document.addEventListener("click", function (e) {
    var open = e.target.closest && e.target.closest("[data-row-open]");
    if (open) {
      var panel = document.getElementById((open.getAttribute("href") || "").slice(1));
      if (!panel) return;
      e.preventDefault();
      panel.classList.add("is-open");
      var first = panel.querySelector("textarea, input, button");
      if (first) first.focus({ preventScroll: true });
      return;
    }
    var close = e.target.closest && e.target.closest("[data-row-close]");
    if (close) {
      e.preventDefault();
      e.stopPropagation();
      var opened = close.closest("[data-row-panel]");
      if (opened) opened.classList.remove("is-open");
    }
  });

  document.addEventListener(
    "keydown",
    function (e) {
      if (e.key !== "Escape") return;
      var opened = document.querySelector("[data-row-panel].is-open");
      if (!opened) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      opened.classList.remove("is-open");
    },
    true
  );

  document.addEventListener("change", function (e) {
    var input = e.target;
    if (!input.matches || !input.matches(".supload__input")) return;
    var zone = zoneOf(input);
    var name = zone && zone.querySelector("[data-upload-name]");
    if (!name) return;
    var chosen = input.files && input.files.length ? input.files[0].name : "";
    name.textContent = chosen || name.dataset.empty || "";
    zone.classList.toggle("has-file", chosen !== "");
  });

  ["dragenter", "dragover"].forEach(function (type) {
    document.addEventListener(type, function (e) {
      var zone = zoneOf(e.target);
      if (zone) zone.classList.add("is-drag");
    });
  });
  ["dragleave", "drop"].forEach(function (type) {
    document.addEventListener(type, function (e) {
      var zone = zoneOf(e.target);
      if (zone) zone.classList.remove("is-drag");
    });
  });
})();
