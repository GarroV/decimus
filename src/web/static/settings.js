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
