/* Мини-апп как приложение аудитора (D373): главная, начало проверки, настройки, Claude, доступ.
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

  /** Подсказки к названию пиццерии: с какого знака и после какой паузы спрашивать. */
  var SUGGEST_MIN = 2;
  var SUGGEST_DELAY_MS = 250;

  var PARENT = { walk: "home", start: "home", settings: "home", help: "settings", claude: "settings", access: "settings" };

  var A = (W.app = { route: null, issued: null, circle: null, stops: null, busy: false, loading: false, wiz: null });

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
    if (route !== "start") A.wiz = null;
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
      top.appendChild(langPill());
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
    if (d.state !== "active" || d.sealed) {
      // Начать проверку можно всегда, когда нет идущей (D392). Сданная для
      // аудитора — как отсутствующая (D400): прошлую карточку не показываем.
      card.appendChild(W.button("walk-mark", tx("walk.app.audit.new"), A.openStart));
      return card;
    }
    var records = (d.zones || []).reduce(function (n, z) { return n + z.recorded.length; }, 0);
    card.appendChild(el("p", "walk-app__card-unit", d.unit));
    card.appendChild(el("p", "walk-app__card-text", W.day(d.date) + " · " + tx("walk.app.audit.records", { count: records })));
    card.appendChild(W.button("walk-mark", tx("walk.app.audit.continue"), function () { A.go("walk"); }));
    card.appendChild(W.button("walk-link", tx("walk.app.audit.new_other"), A.openStart));
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

  /** Язык в настройках: подпись слева, пилюля справа — одной строкой. */
  function langRow() {
    var box = el("div", "walk-app__row");
    box.appendChild(el("span", "walk-app__row-label", tx("walk.app.lang")));
    box.appendChild(langPill());
    return box;
  }

  /** Язык интерфейса пилюлей в шапке главной (D414): тот же выбор, что в настройках. */
  function langPill() {
    var pill = el("div", "walk-app__lang");
    pill.setAttribute("role", "group");
    pill.setAttribute("aria-label", tx("walk.app.lang"));
    (app().langs || []).forEach(function (l) {
      var on = l.code === data().lang;
      var b = W.button("walk-app__lang-opt" + (on ? " is-on" : ""), l.code.toUpperCase(), function () {
        if (on) return;
        act({ op: "lang", lang: l.code }).then(function (body) { if (body) W.apply(body); });
      });
      b.setAttribute("aria-label", l.label);
      b.setAttribute("aria-pressed", on ? "true" : "false");
      pill.appendChild(b);
    });
    return pill;
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
      root.appendChild(el("p", "walk-app__note", tx("walk.app.claude.safety")));
      root.appendChild(el("p", "walk-app__note", tx("walk.app.claude.restart")));
      if (got.expires) root.appendChild(el("p", "walk-app__note", tx("walk.app.claude.expires", { date: got.expires })));
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

  /* ── начало проверки (D392): те же шаги, что у мастера бота, — полями ── */

  function wizardFresh() {
    return {
      opts: null, loading: false, error: "", field: "",
      form: { checklist: "", unit: "", kind: "", speech: "" },
      suggestions: [], ask: null, confirm: false, replaceOk: false, busy: false,
      timer: null, seq: 0, box: null,
    };
  }

  A.openStart = function () {
    A.wiz = wizardFresh();
    A.go("start");
  };

  function wizardFail(wz, message) {
    wz.busy = false;
    wz.loading = false;
    wz.error = message;
    W.haptic("error");
    if (A.wiz === wz) W.render();
  }

  function loadOptions() {
    var wz = A.wiz;
    wz.loading = true;
    W.post(W.urls.start, { op: "options" }).then(function (res) {
      if (A.wiz !== wz) return;
      if (!res.ok) return wizardFail(wz, (res.body && res.body.message) || tx("walk.error"));
      wz.loading = false;
      wz.opts = res.body;
      // Вид и языки предзаполнены — на экране остаётся то, что нельзя угадать.
      wz.form.kind = res.body.kinds.length ? res.body.kinds[0].code : "";
      wz.form.speech = res.body.default_lang;
      if (res.body.checklists.length === 1) wz.form.checklist = res.body.checklists[0].code;
      W.render();
    }).catch(function () {
      if (A.wiz === wz) wizardFail(wz, tx("walk.err.network"));
    });
  }

  /** Ключ сравнения, как `unit_pick._key` на сервере: без тире и пробелов, латиницей. */
  function unitKey(ix, text) {
    var dashes = new RegExp(ix.dashes, "g");
    var flat = text.replace(dashes, "").replace(/\s+/g, "").toLowerCase();
    var out = "";
    for (var i = 0; i < flat.length; i += 1) {
      var ch = flat.charAt(i);
      out += Object.prototype.hasOwnProperty.call(ix.translit, ch) ? ix.translit[ch] : ch;
    }
    return out;
  }

  /** Подсказки по вхождению прямо в телефоне (D414): без запроса на каждую букву. */
  function localSuggestions(wz, typed) {
    var ix = wz.opts && wz.opts.suggest;
    if (!ix || !ix.units || !ix.units.length) return null;
    var key = unitKey(ix, typed);
    if (!key) return null;
    var found = ix.units.filter(function (u) {
      return u.keys.some(function (k) { return k.indexOf(key) !== -1; });
    }).map(function (u) { return u.name; });
    if (!found.length) return null;
    return found.sort().slice(0, ix.limit);
  }

  /** На каждую букву: сначала свой справочник, мгновенно; пусто — сервер с паузой. */
  function onUnitTyped(wz) {
    window.clearTimeout(wz.timer);
    var typed = wz.form.unit.trim();
    wz.seq += 1;
    if (typed.length < SUGGEST_MIN) { wz.suggestions = []; paintSuggestions(wz); return; }
    var local = localSuggestions(wz, typed);
    if (local) { wz.suggestions = local; paintSuggestions(wz); return; }
    wz.timer = window.setTimeout(function () { askSuggestions(wz); }, SUGGEST_DELAY_MS);
  }

  function askSuggestions(wz) {
    var typed = wz.form.unit.trim();
    wz.seq += 1;
    var seq = wz.seq;
    if (typed.length < SUGGEST_MIN) { wz.suggestions = []; paintSuggestions(wz); return; }
    W.post(W.urls.start, { op: "suggest", name: typed }).then(function (res) {
      if (A.wiz !== wz || wz.seq !== seq || !res.ok) return;
      wz.suggestions = res.body.suggestions || [];
      paintSuggestions(wz);
    }).catch(function () { /* подсказки — удобство: без них название вводится так же */ });
  }

  function paintSuggestions(wz) {
    var box = wz.box;
    if (!box) return;
    box.textContent = "";
    wz.suggestions.forEach(function (name) {
      if (name === wz.form.unit.trim()) return;
      box.appendChild(W.button("walk-chip", name, function () {
        wz.form.unit = name;
        wz.suggestions = [];
        wz.ask = null;
        wz.error = "";
        W.render();
      }));
    });
  }

  function complete(wz) {
    var f = wz.form;
    var needList = wz.opts.checklists.length > 1;
    return !!f.unit.trim() && !!f.kind && !!f.speech && (!needList || !!f.checklist);
  }

  function submit(wz, extra) {
    if (wz.busy) return;
    var f = wz.form;
    var body = { op: "start", checklist: f.checklist, unit: f.unit.trim(), kind: f.kind, speech_lang: f.speech };
    if (wz.replaceOk) body.replace = true;
    if (extra && extra.add_unit) body.add_unit = true;
    wz.busy = true;
    wz.error = "";
    wz.field = "";
    W.render();
    W.post(W.urls.start, body).then(function (res) {
      if (A.wiz !== wz) return;
      wz.busy = false;
      if (res.ok) {
        // Обход новой проверки — сразу: экран данных приходит ответом на старт.
        A.wiz = null;
        A.route = "walk";
        A.issued = null;
        A.syncBack();
        W.haptic("success");
        W.apply(res.body);
        window.scrollTo(0, 0);
        return;
      }
      var b = res.body || {};
      W.haptic("error");
      if (b.need === "unit_new") {
        wz.ask = { name: b.name, message: b.message };
      } else if (b.need === "replace") {
        // Проверка началась в чате, пока человек заполнял поля: спросить, как при идущей.
        wz.opts.state = "running";
        wz.replaceOk = false;
        wz.confirm = true;
      } else {
        wz.error = b.message || tx("walk.error");
        wz.field = b.field || "";
      }
      W.render();
    }).catch(function () {
      if (A.wiz === wz) wizardFail(wz, tx("walk.err.network"));
    });
  }

  function onGo(wz) {
    if (!complete(wz) || wz.busy) return;
    // Идущая проверка стирается новой (T052): спросить, а не заменить молча.
    if (wz.opts.state === "running" && !wz.replaceOk) { wz.confirm = true; W.render(); return; }
    submit(wz);
  }

  function field(label) {
    var part = el("div", "walk-form__part");
    part.appendChild(el("label", "walk-form__label", label));
    return part;
  }

  /** Выбор одного из списка кодов: чипы для длинных подписей, сегмент для двух. */
  function choice(wz, key, items, seg) {
    var box = el("div", seg ? "walk-seg" : "walk-chips");
    items.forEach(function (it) {
      var on = wz.form[key] === it.code;
      var cls = (seg ? "walk-seg__opt" : "walk-chip") + (on ? " is-on" : "");
      box.appendChild(W.button(cls, it.label, function () {
        wz.form[key] = it.code;
        wz.error = "";
        W.render();
      }));
    });
    return box;
  }

  /** «?» у языка чек-листа (D414): пояснение раскрывается под подписью. */
  function hintToggle(wz) {
    var b = W.button("walk-app__hint" + (wz.hint ? " is-on" : ""), "?", function () {
      wz.hint = !wz.hint;
      W.render();
    });
    b.type = "button";
    b.setAttribute("aria-label", tx("walk.start.speech_hint_label"));
    b.setAttribute("aria-expanded", wz.hint ? "true" : "false");
    return b;
  }

  function unitField(wz) {
    var part = field(tx("walk.start.unit"));
    var input = el("input", "walk-input");
    input.value = wz.form.unit;
    input.placeholder = tx("walk.start.unit_hint");
    input.setAttribute("aria-label", tx("walk.start.unit"));
    input.autocomplete = "off";
    input.autocapitalize = "words";
    input.addEventListener("input", function () {
      wz.form.unit = input.value;
      wz.ask = null;
      onUnitTyped(wz);
    });
    part.appendChild(input);
    wz.box = el("div", "walk-chips walk-app__suggest");
    part.appendChild(wz.box);
    paintSuggestions(wz);
    if (wz.field === "unit" && wz.error) part.appendChild(el("p", "walk-form__error", wz.error));
    if (wz.ask) {
      // «Новая пиццерия?» — как у бота: добавить в справочник или поправить название.
      var ask = el("div", "walk-app__ask");
      ask.appendChild(el("p", "walk-form__note", wz.ask.message));
      var row = el("div", "walk-seg");
      row.appendChild(W.button("walk-seg__opt is-on", tx("walk.start.new_yes"), function () { submit(wz, { add_unit: true }); }));
      row.appendChild(W.button("walk-seg__opt", tx("walk.start.new_no"), function () { wz.ask = null; W.render(); }));
      ask.appendChild(row);
      part.appendChild(ask);
    }
    return part;
  }

  function replaceConfirm(root, wz) {
    var box = el("section", "walk-app__card");
    box.appendChild(el("h2", "walk-app__card-unit", tx("walk.start.replace_title")));
    box.appendChild(W.button("walk-btn walk-btn--danger", tx("walk.start.replace_yes"), function () {
      wz.replaceOk = true;
      wz.confirm = false;
      submit(wz);
    }));
    box.appendChild(W.button("walk-link", tx("walk.start.keep"), function () { wz.confirm = false; W.render(); }));
    root.appendChild(box);
  }

  function startScreen(root) {
    var wz = A.wiz || (A.wiz = wizardFresh());
    root.appendChild(head(tx("walk.start.title")));
    if (!wz.opts) {
      if (wz.error) {
        root.appendChild(el("p", "walk-form__error", wz.error));
        root.appendChild(W.button("walk-btn", tx("walk.start.cancel"), onBack));
      } else {
        root.appendChild(el("p", "walk__loading", "…"));
        if (!wz.loading) loadOptions();
      }
      return;
    }
    var o = wz.opts;
    // «Идёт проверка…» — один раз: над формой и над подтверждением замены.
    if (o.state === "running") {
      root.appendChild(el("p", "walk-banner", tx("walk.start.running", { unit: data().unit || "—" })));
    }
    if (wz.confirm) return replaceConfirm(root, wz);
    var form = el("form", "walk-app__form");
    form.noValidate = true;
    if (o.checklists.length > 1) {
      var cl = field(tx("walk.start.checklist"));
      cl.appendChild(choice(wz, "checklist", o.checklists.map(function (c) { return { code: c.code, label: c.name }; }), false));
      form.appendChild(cl);
    }
    form.appendChild(unitField(wz));
    var kind = field(tx("walk.start.kind"));
    kind.appendChild(choice(wz, "kind", o.kinds.map(function (k) { return { code: k.code, label: k.title }; }), false));
    form.appendChild(kind);
    var langs = o.langs.map(function (l) { return { code: l.code, label: l.label }; });
    var speech = field(tx("walk.start.speech"));
    var labelRow = el("div", "walk-app__label-row");
    labelRow.appendChild(speech.firstChild);
    labelRow.appendChild(hintToggle(wz));
    speech.appendChild(labelRow);
    if (wz.hint) speech.appendChild(el("p", "walk-app__tip", tx("walk.start.speech_hint")));
    speech.appendChild(choice(wz, "speech", langs, true));
    form.appendChild(speech);
    if (wz.error && wz.field !== "unit") form.appendChild(el("p", "walk-form__error", wz.error));
    var go = W.button("walk-mark walk-app__go", tx(wz.busy ? "walk.start.going" : "walk.start.go"));
    go.type = "submit";
    go.disabled = !complete(wz) || wz.busy;
    form.appendChild(go);
    form.addEventListener("submit", function (e) { e.preventDefault(); onGo(wz); });
    root.appendChild(form);
  }

  var SCREENS = { home: home, start: startScreen, settings: settings, help: help, claude: claude, access: access };

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
