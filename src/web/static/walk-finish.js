/* Мини-апп обхода, D422: «Завершить проверку» из приложения.
 *
 * Нажатие → подтверждение в приложении → `POST /tg/walk/app {op: "finish"}`.
 * Сервер шлёт в чат тот же итог, что даёт `/finish` в боте, и отвечает
 * `sent: true`; пока владелец не включил `WALK_APP_FINISH`, он отвечает
 * `sent: false` — тогда приложение просит команду `/finish` и закрывается
 * так же. После ответа приложение закрывается: человек оказывается в чате.
 */
(function () {
  "use strict";

  var W = window.DecimusWalk;
  var tg = W.tg;
  var tx = W.tx;
  var el = W.el;

  /** Пауза перед закрытием: тост успевают прочесть. */
  var CLOSE_DELAY_MS = 1400;

  var busy = false;

  function closeApp() {
    if (W.inTelegram()) window.setTimeout(function () { tg.close(); }, CLOSE_DELAY_MS);
  }

  function send(done) {
    if (busy) return;
    busy = true;
    W.post(W.urls.app, { op: "finish" }).then(function (res) {
      busy = false;
      if (!res.ok) throw new Error((res.body && res.body.message) || tx("walk.error"));
      W.haptic("success");
      W.toast(res.body.sent ? tx("walk.finish.sent") : tx("walk.finish.manual"), "ok");
      closeApp();
    }).catch(function (err) {
      busy = false;
      W.haptic("error");
      W.toast(err && err.message && err.message !== "Failed to fetch" ? err.message : tx("walk.err.network"), "err");
    }).then(done);
  }

  /** Подтверждение завершения; отказ или тап мимо — ничего не происходит. */
  function ask() {
    if (document.getElementById("walk-confirm")) return;
    var scrim = el("div", "walk-confirm");
    scrim.id = "walk-confirm";
    var card = el("div", "walk-confirm__card");
    card.setAttribute("role", "alertdialog");
    card.setAttribute("aria-modal", "true");
    card.appendChild(el("h2", "walk-confirm__title", tx("walk.finish.title")));
    card.appendChild(el("p", "walk-confirm__text", tx("walk.finish.ask")));
    var row = el("div", "walk-confirm__row");
    function close() { if (scrim.parentNode) scrim.parentNode.removeChild(scrim); }
    var no = W.button("walk-mark is-on", tx("walk.sheet.cancel"), close);
    var yes = W.button("walk-mark", tx("walk.finish.yes"), function () {
      yes.disabled = true;
      send(close);
    });
    row.appendChild(no);
    row.appendChild(yes);
    card.appendChild(row);
    scrim.appendChild(card);
    scrim.addEventListener("click", function (e) { if (e.target === scrim) close(); });
    document.body.appendChild(scrim);
    yes.focus();
  }

  W.finish = { ask: ask };
})();
