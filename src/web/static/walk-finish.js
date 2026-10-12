/* Мини-апп обхода, D422 и D429: «Завершить проверку» из приложения.
 *
 * Нажатие → подтверждение в приложении → `POST /tg/walk/app {op: "finish"}`.
 * Что уходит в чат, решает режим человека из настроек (`app.finish_mode`):
 *
 * - `summary` («Сначала сводка») — тот же итог, что даёт `/finish`; отчёт
 *   человек подтверждает уже в чате;
 * - `report` («Сразу отчёт») — отчёт сразу. Если у страны пиццерии несколько
 *   языков отчёта (`report_langs` из данных экрана), в подтверждении выбирают
 *   язык пилюлями; один язык берётся молча. Не заполнены «Сведения» — сервер
 *   отказывает (409, `reason: "info"`), приложение говорит сколько осталось и
 *   открывает лист «Сведения»: вопросы информационной части живут в боте, веб
 *   их провести не может.
 *
 * После ответа приложение закрывается: человек оказывается в чате.
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

  function isReport() {
    var app = (W.state.data || {}).app || {};
    return app.finish_mode === "report";
  }

  function closeApp() {
    if (W.inTelegram()) window.setTimeout(function () { tg.close(); }, CLOSE_DELAY_MS);
  }

  /** Отправить `body`; `done` — когда подтверждение можно убрать. */
  function send(body, done) {
    if (busy) return;
    busy = true;
    W.post(W.urls.app, body).then(function (res) {
      busy = false;
      if (!res.ok) {
        var err = new Error((res.body && res.body.message) || tx("walk.error"));
        err.reason = res.body && res.body.reason;
        throw err;
      }
      W.haptic("success");
      W.toast(res.body.mode === "report" ? tx("walk.finish.sent_report") : tx("walk.finish.sent"), "ok");
      closeApp();
    }).catch(function (err) {
      busy = false;
      W.haptic("error");
      W.toast(err && err.message && err.message !== "Failed to fetch" ? err.message : tx("walk.err.network"), "err");
      // Сведения не заполнены: показываем, где их заполнить.
      if (err && err.reason === "info" && W.openInfo) {
        done();
        W.openInfo();
        return;
      }
    }).then(done);
  }

  /** Языки отчёта пилюлями: выбранный запоминается в `pick.code`. */
  function langPills(langs, pick) {
    var box = el("div", "walk-confirm__langs");
    box.appendChild(el("p", "walk-confirm__label", tx("walk.finish.report_lang")));
    var pill = el("div", "walk-app__lang walk-app__lang--wide");
    pill.setAttribute("role", "group");
    pill.setAttribute("aria-label", tx("walk.finish.report_lang"));
    var buttons = [];
    langs.forEach(function (l) {
      var b = W.button("walk-app__lang-opt", l.label, function () {
        pick.code = l.code;
        buttons.forEach(function (x) {
          var on = x === b;
          x.classList.toggle("is-on", on);
          x.setAttribute("aria-pressed", on ? "true" : "false");
        });
      });
      b.setAttribute("aria-pressed", "false");
      buttons.push(b);
      pill.appendChild(b);
    });
    box.appendChild(pill);
    return box;
  }

  /** Подтверждение завершения; отказ или тап мимо — ничего не происходит. */
  function ask() {
    if (document.getElementById("walk-confirm")) return;
    var report = isReport();
    var langs = report ? (W.state.data.report_langs || []) : [];
    var pick = { code: langs.length === 1 ? langs[0].code : null };
    var scrim = el("div", "walk-confirm");
    scrim.id = "walk-confirm";
    var card = el("div", "walk-confirm__card");
    card.setAttribute("role", "alertdialog");
    card.setAttribute("aria-modal", "true");
    card.appendChild(el("h2", "walk-confirm__title", tx("walk.finish.title")));
    card.appendChild(el("p", "walk-confirm__text", tx(report ? "walk.finish.ask_report" : "walk.finish.ask")));
    if (langs.length > 1) card.appendChild(langPills(langs, pick));
    var row = el("div", "walk-confirm__row");
    function close() { if (scrim.parentNode) scrim.parentNode.removeChild(scrim); }
    var no = W.button("walk-mark is-on", tx("walk.sheet.cancel"), close);
    var yes = W.button("walk-mark", tx(report ? "walk.finish.yes_report" : "walk.finish.yes"), function () {
      if (report && langs.length > 1 && !pick.code) {
        W.haptic("error");
        W.toast(tx("walk.finish.err.lang"), "err");
        return;
      }
      yes.disabled = true;
      send(report ? { op: "finish", report_lang: pick.code } : { op: "finish" }, close);
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
