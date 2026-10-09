/* Мини-апп как приложение аудитора (D373): главная, настройки, Claude, доступ.
 *
 * Обход — один раздел приложения. Этот файл держит всё вокруг него: куда
 * человек попадает при открытии, как возвращается назад и где настройки.
 * Разделы перечислены на главной из ответа сервера (`app.sections`): новый
 * раздел (проверка конкурентов и др.) — это ещё одна карточка и свой экран,
 * а не правка обхода.
 *
 * Навигация — без адресов: экран один, маршрут в памяти (`W.app.route`).
 * «Назад» — системная кнопка Telegram; её обработчик вешается ОДИН раз при
 * загрузке, раньше обработчиков форм, и молчит, пока открыта форма или лист:
 * Telegram зовёт все обработчики по очереди, и форма закрывается своим.
 */
(function () {
  "use strict";

  var W = window.DecimusWalk;
  var tg = W.tg;
  var el = W.el;
  var tx = W.tx;

  /** Куда ведёт «Назад» с каждого экрана. */
  /** Период отказов мастера на экране доступа — неделя, как у `/stops`. */
  var STOPS_DAYS = 7;

  var PARENT = { walk: "home", settings: "home", help: "settings", claude: "settings", access: "settings" };

  var A = (W.app = { route: null, issued: null, circle: null, stops: null, busy: false, loading: false });

  function data() { return W.state.data || {}; }
  function app() { return data().app || {}; }

  function layerOpen() {
    return (W.sheet && W.sheet.isOpen()) || W.state.info || (W.menu && W.menu.isOpen());
  }

  /** Первый экран: идёт проверка — сразу обход, иначе главная. */
  A.start = function () {
    if (A.route !== null) return;
    var d = data();
    A.route = d.state === "active" && !d.sealed ? "walk" : "home";
    A.syncBack();
  };

  A.showsWalk = function () { return A.route === "walk" && data().state === "active"; };

  A.go = function (route) {
    A.route = route;
    if (route !== "claude") A.issued = null;
    A.syncBack();
    W.render();
    window.scrollTo(0, 0);
  };

  A.syncBack = function () {
    if (!W.supports("6.1")) return;
    if (A.route && A.route !== "home") tg.BackButton.show();
    else tg.BackButton.hide();
  };

  function onBack() {
    if (layerOpen()) return;
    A.go(PARENT[A.route] || "home");
  }

  /* ── общие кусочки ─────────────────────────────────────────────────── */

  function head(title, gear) {
    var top = el("header", "walk-app__head");
    if (A.route !== "home") {
      top.appendChild(W.button("walk-sheet__back", "‹ " + tx("walk.sheet.back"), onBack));
    }
    top.appendChild(el("h1", "walk-app__title", title));
    if (gear) {
      var g = W.button("walk-app__gear", "⚙", function () { A.go("settings"); });
      g.setAttribute("aria-label", tx("walk.app.settings"));
      top.appendChild(g);
    }
    return top;
  }

  function row(label, value, onClick) {
    var r = onClick ? W.button("walk-app__row is-link", null, onClick) : el("div", "walk-app__row");
    r.appendChild(el("span", "walk-app__row-label", label));
    if (value) r.appendChild(el("span", "walk-app__row-value", value));
    if (onClick) r.appendChild(el("span", "walk-app__chev", "›"));
    return r;
  }

  function fail(res) {
    throw new Error((res.body && res.body.message) || tx("walk.error"));
  }

  function act(body) {
    if (A.busy) return Promise.resolve(null);
    A.busy = true;
    return W.post(W.urls.app, body).then(function (res) {
      A.busy = false;
      if (!res.ok) fail(res);
      return res.body;
    }).catch(function (err) {
      A.busy = false;
      W.haptic("error");
      W.toast(err && err.message && err.message !== "Failed to fetch" ? err.message : tx("walk.err.network"), "err");
      return null;
    });
  }

  /* ── главная ───────────────────────────────────────────────────────── */

  function auditCard() {
    var d = data();
    var card = el("section", "walk-app__card");
    card.appendChild(el("h2", "walk-app__card-title", tx("walk.app.audit")));
    if (d.state !== "active") {
      card.appendChild(el("p", "walk-app__card-text", tx("walk.app.audit.none")));
      if (W.inTelegram()) card.appendChild(W.button("walk-mark", tx("walk.app.audit.to_chat"), function () { tg.close(); }));
      return card;
    }
    var records = (d.zones || []).reduce(function (n, z) { return n + z.recorded.length; }, 0);
    card.appendChild(el("p", "walk-app__card-unit", d.unit));
    card.appendChild(el("p", "walk-app__card-text", W.day(d.date) + " · " + tx("walk.app.audit.records", { count: records })));
    if (d.sealed) card.appendChild(el("p", "walk-banner", tx("walk.app.audit.sealed")));
    card.appendChild(W.button("walk-mark", tx(d.sealed ? "walk.app.audit.open" : "walk.app.audit.continue"), function () { A.go("walk"); }));
    return card;
  }

  /** Разделы приложения. Сейчас один; следующий — ещё одна карточка. */
  var SECTIONS = { audit: auditCard };

  function home(root) {
    root.appendChild(head("Decimus", true));
    (app().sections || ["audit"]).forEach(function (code) {
      if (SECTIONS[code]) root.appendChild(SECTIONS[code]());
    });
  }

  /* ── настройки ─────────────────────────────────────────────────────── */

  function langRow() {
    var box = el("div", "walk-app__row walk-app__row--stack");
    box.appendChild(el("span", "walk-app__row-label", tx("walk.app.lang")));
    var seg = el("div", "walk-seg");
    (app().langs || []).forEach(function (l) {
      var on = l.code === data().lang;
      seg.appendChild(W.button("walk-seg__opt" + (on ? " is-on" : ""), l.label, function () {
        if (on) return;
        act({ op: "lang", lang: l.code }).then(function (body) { if (body) W.apply(body); });
      }));
    });
    box.appendChild(seg);
    return box;
  }

  function settings(root) {
    root.appendChild(head(tx("walk.app.settings")));
    var list = el("section", "walk-app__list");
    list.appendChild(langRow());
    list.appendChild(row(tx("walk.app.help"), null, function () { A.go("help"); }));
    if (app().circle) {
      list.appendChild(row(tx("walk.app.claude"), null, function () { A.go("claude"); }));
      list.appendChild(row(tx("walk.app.access"), null, function () { A.go("access"); }));
    }
    list.appendChild(row(tx("walk.app.version"), app().version || "—"));
    root.appendChild(list);
  }

  function help(root) {
    root.appendChild(head(tx("walk.app.help")));
    root.appendChild(el("p", "walk-app__prose", tx("walk.app.help.text")));
  }

  /* ── подключить Claude: команда показывается один раз ──────────────── */

  function copy(text) {
    var done = function () { W.haptic("success"); W.toast(tx("walk.app.claude.copied"), "ok"); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () { selectCode(); });
    } else {
      selectCode();
    }
  }

  function selectCode() {
    var code = document.querySelector(".walk-app__code");
    if (!code) return;
    var range = document.createRange();
    range.selectNodeContents(code);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  }

  function claude(root) {
    root.appendChild(head(tx("walk.app.claude")));
    root.appendChild(el("p", "walk-app__prose", tx("walk.app.claude.text")));
    var got = A.issued;
    if (got) {
      root.appendChild(el("pre", "walk-app__code", got.command));
      root.appendChild(W.button("walk-mark", tx("walk.app.claude.copy"), function () { copy(got.command); }));
      root.appendChild(el("p", "walk-app__note", tx("walk.app.claude.restart")));
      if (got.replaced) root.appendChild(el("p", "walk-banner", tx("walk.app.claude.replaced")));
    }
    root.appendChild(W.button(got ? "walk-btn" : "walk-mark", tx(got ? "walk.app.claude.again" : "walk.app.claude.issue"), function () {
      act({ op: "mcp_issue" }).then(function (body) {
        if (!body) return;
        A.issued = body;
        W.render();
      });
    }));
  }

  /* ── доступ к Claude: круг и отказы мастера ────────────────────────── */

  /** Круг, затем отказы — по очереди: `act` держит одно действие за раз. */
  function loadAccess() {
    A.loading = true;
    act({ op: "mcp_who" }).then(function (body) {
      A.circle = body ? body.circle : [];
      return act({ op: "stops", days: STOPS_DAYS });
    }).then(function (body) {
      A.loading = false;
      A.stops = body ? body.stops : null;
      if (A.route === "access") W.render();
    });
  }

  function person(p) {
    var r = el("div", "walk-app__row");
    var who = el("span", "walk-app__row-label", p.name ? p.name + " · " + p.id : String(p.id));
    r.appendChild(who);
    var state = p.founder ? tx("walk.app.access.founder") : !p.live ? tx("walk.app.access.revoked")
      : tx(p.token ? "walk.app.access.token" : "walk.app.access.no_token");
    r.appendChild(el("span", "walk-app__row-value", state));
    if (p.live && !p.founder) {
      r.appendChild(W.button("walk-btn walk-btn--small walk-btn--danger", tx("walk.app.access.revoke"), function () {
        act({ op: "mcp_revoke", id: p.id }).then(function (body) { if (body) { A.circle = body.circle; W.render(); } });
      }));
    }
    return r;
  }

  function addForm() {
    var form = el("form", "walk-app__add");
    var input = el("input", "walk-input");
    input.inputMode = "numeric";
    input.placeholder = tx("walk.app.access.id");
    input.setAttribute("aria-label", tx("walk.app.access.id"));
    form.appendChild(input);
    form.appendChild(W.button("walk-btn", tx("walk.app.access.add")));
    form.lastChild.type = "submit";
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      act({ op: "mcp_add", id: input.value.trim() }).then(function (body) { if (body) { A.circle = body.circle; W.render(); } });
    });
    return form;
  }

  function access(root) {
    root.appendChild(head(tx("walk.app.access")));
    if (A.circle === null) {
      root.appendChild(el("p", "walk__loading", "…"));
      if (!A.loading) loadAccess();
      return;
    }
    var list = el("section", "walk-app__list");
    if (!A.circle.length) list.appendChild(el("p", "walk-app__note", tx("walk.app.access.empty")));
    A.circle.forEach(function (p) { list.appendChild(person(p)); });
    root.appendChild(list);
    root.appendChild(addForm());
    root.appendChild(el("h2", "walk-app__subtitle", tx("walk.app.stops") + " · " + tx("walk.app.stops.period", { days: STOPS_DAYS })));
    var stops = el("section", "walk-app__list");
    if (A.stops && !A.stops.length) stops.appendChild(el("p", "walk-app__note", tx("walk.app.stops.empty")));
    (A.stops || []).forEach(function (s) {
      stops.appendChild(row(s.step + " · " + s.reason, tx("walk.app.stops.line", { times: s.times, people: s.people })));
    });
    root.appendChild(stops);
  }

  var SCREENS = { home: home, settings: settings, help: help, claude: claude, access: access };

  A.render = function (root) {
    if (A.route !== "access") { A.circle = null; A.stops = null; }
    (SCREENS[A.route] || home)(root);
  };

  /* ── системные кнопки Telegram ─────────────────────────────────────── */

  if (W.supports("6.1")) tg.BackButton.onClick(onBack);
  // «Настройки» в меню ⋮ над мини-аппом (Bot API 7.0) — второй вход к ⚙.
  if (W.supports("7.0") && tg.SettingsButton) {
    tg.SettingsButton.onClick(function () { if (!layerOpen()) A.go("settings"); });
    tg.SettingsButton.show();
  }
})();
