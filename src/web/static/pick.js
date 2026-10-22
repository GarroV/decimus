// Отбор (`_pick.html`) — `<select>`, пункты которого хранят адрес перехода:
// выбрал — страница перестроилась, кнопки не нужно. Не загрузился скрипт — под
// <noscript> те же варианты лежат ссылками.
// Заодно: выпадающие панели `<details class="pick">` (период) закрываются сами
// кликом мимо и клавишей Esc; соседнюю при открытии новой закрывает атрибут
// `name` — без скрипта.
(function () {
  "use strict";
  document.addEventListener("change", function (event) {
    var select = event.target;
    if (select && select.matches && select.matches("select[data-pick-nav]") && select.value) {
      if (select.hasAttribute("data-drawer-open")) {
        // Переход внутри панели справа: щелчок по ссылке-двойнику ловит `split.js`.
        var link = document.createElement("a");
        link.href = select.value;
        link.setAttribute("data-drawer-open", "");
        link.hidden = true;
        document.body.appendChild(link);
        link.click();
        link.remove();
        return;
      }
      window.location.href = select.value;
    }
  });
  function openPicks() {
    return document.querySelectorAll("details.pick[open]");
  }
  document.addEventListener("click", function (event) {
    openPicks().forEach(function (pick) {
      if (!pick.contains(event.target)) pick.removeAttribute("open");
    });
  });
  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    openPicks().forEach(function (pick) {
      pick.removeAttribute("open");
      var summary = pick.querySelector("summary");
      if (summary) summary.focus();
    });
  });
})();
