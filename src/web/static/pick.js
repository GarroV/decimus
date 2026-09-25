// Чипы отбора (`_pick.html`) закрываются сами: кликом мимо и клавишей Esc.
// Соседний чип при открытии нового закрывает атрибут `name` у <details> —
// без скрипта. Этот файл только добавляет удобство: не загрузился — чипы
// открываются и закрываются, как раньше, собственным кликом.
(function () {
  "use strict";
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
