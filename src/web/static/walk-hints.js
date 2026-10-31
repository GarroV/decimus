/* Мини-апп: подсказки по долгому нажатию и обучение из них (D444).
 *
 * Любой элемент с `data-hint="<ключ>"`, зажатый примерно на полсекунды, поднимает
 * лист снизу в стиле контекстного меню (`walk-menu.css`): заголовок и пара строк
 * из `walk.hint.<ключ>.title|text`. Обучение — те же подсказки по очереди: затемнение
 * с «окном» вокруг элемента и тот же лист. Жесты слушает один обработчик на
 * документе, поэтому перерисовка экрана ему не мешает.
 *
 * Что где лежит: настройки человека (`hints` — вкл/выкл, `welcomed`, `home`, `walk` —
 * пройдены ли части обучения) — одним ключом `walk-hints`: в CloudStorage Telegram
 * (у самого человека, на всех его устройствах), вне Telegram — в localStorage,
 * как личные пометки обхода (`walk.js`). Сервер их не знает.
 *
 *   W.hints.afterRender()       — зовёт `render()`: приветствие и часть обучения «обход»
 *   W.hints.settingsRows(list)  — строки «Подсказки» и «Пройти обучение заново»
 *   W.hints.startTour("home")   — ручной запуск части обучения
 */
(function () {
  "use strict";

  var W = window.DecimusWalk;
  var tg = W.tg;
  var el = W.el;
  var tx = W.tx;

  var LONG_PRESS_MS = 500;
  var MOVE_CANCEL_PX = 10;
  /** Сколько после долгого нажатия глотать «клик» от того же касания. */
  var SWALLOW_MS = 600;
  var TOUR_DELAY_MS = 350;
  var SPOT_PAD_PX = 6;
  var SPOT_RADIUS_PX = 14;
  var PREFS_KEY = "walk-hints";

  /** Части обучения: ключи подсказок по порядку. */
  var PARTS = {
    home: ["start", "lang", "settings"],
    walk: ["zones", "add", "checklist", "next", "info", "finish", "final"],
  };
  var NO_TARGET = "final";

  var prefs = null;
  var sheetNode = null;
  var tour = null;
  var pending = false;

  /* ── настройки человека ────────────────────────────────────────────── */

  function hasCloud() { return W.supports("6.9") && !!tg.CloudStorage; }

  function parsePrefs(raw) {
    var v = {};
    try { v = JSON.parse(raw || "{}") || {}; } catch (e) { v = {}; }
    return {
      hints: v.hints !== false,
      welcomed: v.welcomed === true,
      home: v.home === true,
      walk: v.walk === true,
    };
  }

  function loadPrefs() {
    var done = function (raw) { prefs = parsePrefs(raw); W.hints.afterRender(); };
    W.storedGet(PREFS_KEY, done);
  }

  function savePrefs(change) {
    prefs = Object.assign({}, prefs || parsePrefs(null), change);
    var raw = JSON.stringify(prefs);
    if (hasCloud()) { tg.CloudStorage.setItem(PREFS_KEY, raw); return; }
    try { window.localStorage.setItem(PREFS_KEY, raw); } catch (e) { /* живёт до закрытия */ }
  }

  function hintsOn() { return !!prefs && prefs.hints; }

  /* ── лист в стиле меню ─────────────────────────────────────────────── */

  function closeSheet() {
    if (!sheetNode) return;
    sheetNode.remove();
    sheetNode = null;
    document.removeEventListener("keydown", onSheetKey);
  }

  function onSheetKey(e) { if (e.key === "Escape") closeSheet(); }

  function paragraphs(text) {
    var box = el("div", "walk-hintsheet__text");
    String(text).split("\n").forEach(function (line) { box.appendChild(el("p", null, line)); });
    return box;
  }

  /** Лист снизу: те же классы и та же анимация, что у `walk-menu.js`. */
  function openSheet(title, text, buttons, onDismiss) {
    closeSheet();
    var node = el("div", "walk-menu walk-hintsheet");
    node.setAttribute("role", "dialog");
    node.setAttribute("aria-modal", "true");
    function dismiss() { closeSheet(); if (onDismiss) onDismiss(); }
    var shade = W.button("walk-menu__shade", null, dismiss);
    shade.setAttribute("aria-label", tx("walk.sheet.close"));
    node.appendChild(shade);
    var panel = el("div", "walk-menu__panel");
    var head = el("div", "walk-menu__head");
    head.appendChild(el("h3", "walk-menu__title", title));
    var x = W.button("walk-menu__close", "✕", dismiss);
    x.setAttribute("aria-label", tx("walk.sheet.close"));
    head.appendChild(x);
    panel.appendChild(head);
    panel.appendChild(paragraphs(text));
    if (buttons && buttons.length) {
      var row = el("div", "walk-hintsheet__actions");
      buttons.forEach(function (b) { row.appendChild(b); });
      panel.appendChild(row);
    }
    node.appendChild(panel);
    document.body.appendChild(node);
    document.addEventListener("keydown", onSheetKey);
    sheetNode = node;
  }

  function showHint(key) {
    var title = tx("walk.hint." + key + ".title");
    if (title === "walk.hint." + key + ".title") return;
    openSheet(title, tx("walk.hint." + key + ".text"));
  }

  /* ── долгое нажатие ────────────────────────────────────────────────── */

  var press = null;
  var fired = false;
  var swallowUntil = 0;

  function cancelPress() {
    if (press) window.clearTimeout(press.timer);
    press = null;
  }

  function hintOf(node) { return node && node.closest ? node.closest("[data-hint]") : null; }

  document.addEventListener("pointerdown", function (e) {
    cancelPress();
    fired = false;
    if (tour || !hintsOn() || (e.pointerType === "mouse" && e.button !== 0)) return;
    var target = hintOf(e.target);
    if (!target) return;
    press = {
      x: e.clientX,
      y: e.clientY,
      timer: window.setTimeout(function () {
        press = null;
        fired = true;
        W.haptic();
        showHint(target.getAttribute("data-hint"));
      }, LONG_PRESS_MS),
    };
  }, { passive: true });

  document.addEventListener("pointermove", function (e) {
    if (!press) return;
    if (Math.hypot(e.clientX - press.x, e.clientY - press.y) > MOVE_CANCEL_PX) cancelPress();
  }, { passive: true });

  function release() {
    cancelPress();
    if (fired) swallowUntil = Date.now() + SWALLOW_MS;
  }
  document.addEventListener("pointerup", release, { passive: true });
  document.addEventListener("pointercancel", release, { passive: true });
  window.addEventListener("scroll", cancelPress, { capture: true, passive: true });

  // Клик, которым кончается долгое нажатие, не должен ничего нажать.
  document.addEventListener("click", function (e) {
    if (Date.now() >= swallowUntil) return;
    swallowUntil = 0;
    e.preventDefault();
    e.stopPropagation();
  }, true);

  // iOS/Android на долгом нажатии зовут своё меню — на подсказках оно не нужно.
  document.addEventListener("contextmenu", function (e) {
    if (hintsOn() && hintOf(e.target)) e.preventDefault();
  });

  /* ── обучение: затемнение с окном и лист ───────────────────────────── */

  function visibleTarget(key) {
    if (key === NO_TARGET) return null;
    var nodes = document.querySelectorAll('[data-hint="' + key + '"]');
    for (var i = 0; i < nodes.length; i++) {
      var r = nodes[i].getBoundingClientRect();
      if (r.width > 0 && r.height > 0) return nodes[i];
    }
    return null;
  }

  function stepKeys(part) {
    return PARTS[part].filter(function (k) { return k === NO_TARGET || !!visibleTarget(k); });
  }

  function placeSpot(target) {
    var s = tour.spot;
    if (!target) {
      s.classList.add("is-none");
      s.style.cssText = "left:50%;top:38%;width:0;height:0";
      return;
    }
    var r = target.getBoundingClientRect();
    s.classList.remove("is-none");
    s.style.left = Math.max(0, r.left - SPOT_PAD_PX) + "px";
    s.style.top = Math.max(0, r.top - SPOT_PAD_PX) + "px";
    s.style.width = Math.min(window.innerWidth, r.width + SPOT_PAD_PX * 2) + "px";
    s.style.height = r.height + SPOT_PAD_PX * 2 + "px";
    s.style.borderRadius = Math.min(SPOT_RADIUS_PX, (r.height + SPOT_PAD_PX * 2) / 2) + "px";
  }

  function drawPanel(key, target) {
    if (tour.panel) tour.panel.remove();
    var keys = tour.keys;
    var at = tour.at;
    var last = at === keys.length - 1;
    // Цель в нижней половине — лист встаёт сверху, чтобы не закрыть её.
    var low = !!target && target.getBoundingClientRect().top > window.innerHeight * 0.42;
    var dock = el("div", "walk-tour__dock" + (low ? " is-top" : ""));
    var panel = el("div", "walk-menu__panel walk-tour__panel");
    var head = el("div", "walk-menu__head");
    head.appendChild(el("h3", "walk-menu__title", tx("walk.hint." + key + ".title")));
    panel.appendChild(head);
    panel.appendChild(paragraphs(tx("walk.hint." + key + ".text")));
    var row = el("div", "walk-tour__row");
    row.appendChild(el("span", "walk-tour__count", tx("walk.tour.step", { n: at + 1, total: keys.length })));
    if (!last) row.appendChild(W.button("walk-link walk-link--quiet walk-tour__skip", tx("walk.tour.skip"), function () { endTour(false); }));
    row.appendChild(W.button("walk-mark walk-tour__next", tx(last ? "walk.tour.done" : "walk.tour.next"), function () {
      W.haptic();
      if (last) endTour(true); else goStep(at + 1);
    }));
    panel.appendChild(row);
    dock.appendChild(panel);
    tour.node.appendChild(dock);
    tour.panel = dock;
  }

  function goStep(at) {
    tour.at = at;
    var key = tour.keys[at];
    var target = visibleTarget(key);
    if (target) target.scrollIntoView({ block: "center", behavior: "auto" });
    window.requestAnimationFrame(function () {
      if (!tour) return;
      placeSpot(target);
      drawPanel(key, target);
    });
  }

  function onTourKey(e) { if (e.key === "Escape") endTour(false); }

  function reposition() {
    if (!tour) return;
    var key = tour.keys[tour.at];
    placeSpot(visibleTarget(key));
  }

  function endTour(finished) {
    if (!tour) return;
    var part = tour.part;
    tour.node.remove();
    document.removeEventListener("keydown", onTourKey);
    window.removeEventListener("resize", reposition);
    tour = null;
    if (finished) savePrefs(part === "home" ? { home: true } : { walk: true });
    else savePrefs({ home: true, walk: true });
  }

  function startTour(part) {
    if (tour) return;
    closeSheet();
    var keys = stepKeys(part);
    if (keys.length === 0) return;
    var node = el("div", "walk-tour");
    node.setAttribute("role", "dialog");
    node.setAttribute("aria-modal", "true");
    var spot = el("div", "walk-tour__spot is-none");
    node.appendChild(spot);
    document.body.appendChild(node);
    tour = { node: node, spot: spot, part: part, keys: keys, at: 0, panel: null };
    document.addEventListener("keydown", onTourKey);
    window.addEventListener("resize", reposition);
    goStep(0);
  }

  /* ── приветствие и вход в обучение ─────────────────────────────────── */

  function welcome() {
    var show = W.button("walk-mark", tx("walk.tour.welcome.show"), function () {
      savePrefs({ welcomed: true });
      closeSheet();
      window.setTimeout(function () { startTour("home"); }, TOUR_DELAY_MS);
    });
    var later = W.button("walk-link walk-link--quiet", tx("walk.tour.welcome.later"), function () {
      closeSheet();
      savePrefs({ welcomed: true, home: true, walk: true });
    });
    // Закрыть мимо кнопок — то же, что «Не сейчас»: спрашивать второй раз не будем.
    openSheet(tx("walk.tour.welcome.title"), tx("walk.tour.welcome.text"), [show, later], function () {
      savePrefs({ welcomed: true, home: true, walk: true });
    });
  }

  function busy() {
    return !!tour || !!sheetNode || (W.sheet && W.sheet.isOpen()) || (W.menu && W.menu.isOpen()) ||
      !!W.state.info || !!document.getElementById("walk-confirm");
  }

  function afterRender() {
    if (tour) {
      var onScreen = (tour.part === "walk") === W.app.showsWalk();
      if (!onScreen) endTour(false); else reposition();
      return;
    }
    if (!prefs || !W.state.data || !W.state.data.texts || pending || busy()) return;
    if (W.app.route === "home" && !prefs.welcomed) {
      pending = true;
      window.setTimeout(function () { pending = false; if (!busy() && W.app.route === "home") welcome(); }, TOUR_DELAY_MS);
    } else if (W.app.showsWalk() && prefs.welcomed && !prefs.walk) {
      pending = true;
      window.setTimeout(function () { pending = false; if (!busy() && W.app.showsWalk()) startTour("walk"); }, TOUR_DELAY_MS);
    }
  }

  /* ── строки настроек ───────────────────────────────────────────────── */

  function settingsRows(list) {
    var box = el("div", "walk-app__row");
    box.appendChild(el("span", "walk-app__row-label", tx("walk.app.hints")));
    var pill = el("div", "walk-app__lang");
    pill.setAttribute("role", "group");
    pill.setAttribute("aria-label", tx("walk.app.hints"));
    [[true, "walk.app.hints.on"], [false, "walk.app.hints.off"]].forEach(function (o) {
      var on = hintsOn() === o[0];
      var b = W.button("walk-app__lang-opt" + (on ? " is-on" : ""), tx(o[1]), function () {
        if (on) return;
        savePrefs({ hints: o[0] });
        W.render();
      });
      b.setAttribute("aria-pressed", on ? "true" : "false");
      pill.appendChild(b);
    });
    box.appendChild(pill);
    list.appendChild(box);
    var again = W.button("walk-app__row is-link walk-app__row--quiet", null, function () {
      savePrefs({ welcomed: true, home: false, walk: false });
      W.app.go("home");
      window.setTimeout(function () { startTour("home"); }, TOUR_DELAY_MS);
    });
    again.appendChild(el("span", "walk-app__row-label", tx("walk.app.tour")));
    again.appendChild(el("span", "walk-app__chev", "›"));
    list.appendChild(again);
  }

  // Скрытие касается только памятки: запись и её кнопка остаются неизменными.
  var hiddenChecklist = {};
  function decorateChecklist(row, opts) {
    var item = row.querySelector(".walk-cl__item");
    if (!item) return;
    var key = (W.state.data.key || "") + "|" + opts.zone + "|" + opts.code;
    var toggle = W.button("walk-cl__visibility", null, function () { setHidden(!hiddenChecklist[key]); });
    function setHidden(hidden) {
      hiddenChecklist[key] = hidden;
      item.hidden = hidden;
      row.classList.toggle("is-hidden", hidden);
      toggle.textContent = tx(hidden ? "walk.cl.show" : "walk.cl.hide");
      toggle.setAttribute("aria-expanded", String(!hidden));
      toggle.setAttribute("aria-label", toggle.textContent + ": " + item.querySelector(".walk-cl__text").textContent);
    }
    row.appendChild(toggle);
    setHidden(!!hiddenChecklist[key]);
    var touch = null;
    var suppressClick = false;
    row.addEventListener("touchstart", function (e) {
      touch = e.touches.length === 1 ? { x: e.touches[0].clientX, y: e.touches[0].clientY } : null;
    }, { passive: true });
    row.addEventListener("touchcancel", function () { touch = null; }, { passive: true });
    row.addEventListener("touchend", function (e) {
      if (!touch) return;
      var dx = e.changedTouches[0].clientX - touch.x;
      var dy = e.changedTouches[0].clientY - touch.y;
      touch = null;
      if (Math.abs(dx) < 60 || Math.abs(dx) <= Math.abs(dy) * 1.5) return;
      // Не переключать зону тем же жестом, которым скрыли пункт.
      e.stopPropagation();
      suppressClick = true;
      window.setTimeout(function () { suppressClick = false; }, 600);
      setHidden(dx < 0);
    }, { passive: true });
    row.addEventListener("click", function (e) {
      if (!suppressClick) return;
      suppressClick = false;
      e.preventDefault();
      e.stopPropagation();
    }, true);
  }

  W.hints = { afterRender: afterRender, settingsRows: settingsRows, startTour: startTour, decorateChecklist: decorateChecklist };
  loadPrefs();
})();
