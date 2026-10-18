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
