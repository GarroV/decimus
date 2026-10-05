// Тема ставится ДО первой отрисовки, иначе тёмная мигает светлой на каждом
// переходе. Поэтому файл подключается в <head> БЕЗ defer — и поэтому он
// отдельный файл, а не встроенный <script>: политика источников (#489)
// встроенные скрипты не исполняет. Выбор человека — в localStorage, «как в
// системе» — отсутствие записи (как в Swarm). Кнопки выбора — в shell.js.
(function () {
  "use strict";
  try {
    var media = matchMedia("(prefers-color-scheme: dark)");
    var STORE = "decimus-theme";
    var apply = function () {
      var chosen = null;
      try { chosen = localStorage.getItem(STORE); } catch (e) { /* приватный режим */ }
      var dark = chosen === "dark" || (chosen !== "light" && media.matches);
      document.documentElement.dataset.theme = dark ? "dark" : "light";
    };
    apply();
    media.addEventListener("change", apply);
  } catch (e) { /* без matchMedia остаётся светлая тема из CSS */ }
})();
