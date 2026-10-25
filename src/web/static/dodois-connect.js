/* Публичная страница входа в Dodo IS по ссылке (D640): пока вход идёт, раз в несколько секунд
   спрашивает СВОЙ сервер о состоянии и, когда оно сменилось, перезагружает страницу (GET —
   он ничего не начинает). Кода устройства Dodo IS в браузере нет. Без скрипта страницу
   достаточно обновить вручную. */
(function () {
  "use strict";
  var root = document.getElementById("dodois-connect");
  if (!root || !root.dataset.statusUrl) return;
  var every = (parseInt(root.dataset.pollSec, 10) || 3) * 1000;
  var failures = 0;
  function tick() {
    fetch(root.dataset.statusUrl, { credentials: "omit", cache: "no-store", referrerPolicy: "no-referrer" })
      .then(function (answer) { return answer.ok ? answer.json() : Promise.reject(new Error("status")); })
      .then(function (data) {
        failures = 0;
        if (data.state !== "pending") { window.location.reload(); return; }
        setTimeout(tick, every);
      })
      .catch(function () {
        failures += 1;
        if (failures < 20) setTimeout(tick, every);
      });
  }
  setTimeout(tick, every);
})();
