// «Настройки» (D470): плитки подключений выбираются ссылкой `?tile=`, скрипт
// не нужен. Он лишь переводит старые якоря (`/settings#claude`, `#bot`,
// `#google`, `#claude-token`) в выбор плитки: закладки и письма со ссылкой
// на якорь продолжают вести в нужную панель.
(function () {
  "use strict";
  var TILE_BY_HASH = {
    "#claude": "claude", "#claude-token": "claude", "#claude-connect": "claude",
    "#bot": "bot", "#google": "google", "#google-link": "google", "#google-unlink": "google",
  };
  var tile = TILE_BY_HASH[location.hash];
  if (!tile) return;
  var params = new URLSearchParams(location.search);
  if (params.has("tile")) return;
  params.set("tile", tile);
  location.replace(location.pathname + "?" + params.toString() + "#connections");
})();

// «Инструкции для проекта» (D476): раскрытие блока кладёт текст в буфер — одно
// нажатие, как в Swarm. Не вышло (нет буфера, нет разрешения) — текст виден в
// блоке, и его берут руками; кнопка «Скопировать ещё раз» остаётся.
(function () {
  "use strict";
  document.querySelectorAll("details[data-copy-on-open]").forEach(function (box) {
    var text = box.querySelector("pre");
    var summary = box.querySelector("summary");
    if (!text || !summary || !navigator.clipboard) return;
    var label = summary.textContent;
    box.addEventListener("toggle", function () {
      if (!box.open) { summary.textContent = label; return; }
      navigator.clipboard.writeText(text.textContent.trim()).then(function () {
        summary.textContent = box.dataset.copied;
      }, function () { /* буфер недоступен — текст виден в блоке */ });
    });
  });
})();
