// Тур по интерфейсу (D756): контроллер. Шаги, тексты и подписи приходят от сервера готовыми
// (`onboarding_tour.py`, атрибут `data-tour-config` на странице); здесь только запуск.
//
// Библиотека (driver.js 1.9.0, MIT, `static/vendor/driver/`) и стили подгружаются при
// запуске: человеку, который тур не открывал, они ничего не стоят. Страница без этого
// файла работает как раньше — кнопки тура в меню учётки остаются скрытыми.
//
// Тур одностраничный: левая панель, поиск, колокольчик и меню учётки есть на каждом экране.
// Берутся шаги, чьи цели видны сейчас: на телефоне нет боковой панели, и шаги групп
// сменяются шагом нижней панели. Группа пунктов подсвечивается невидимой рамкой по их
// общему прямоугольнику (`.tour-span`).
//
// Автозапуск (партнёру, первый раз) отмечается сразу при старте — «показан»: закрыл тур,
// перезагрузил страницу или ушёл по ссылке — второй раз он сам не откроется. Повтор из меню
// учётки ничего не отмечает.
(function () {
  "use strict";

  var holder = document.querySelector("[data-tour-config]");
  if (!holder) return;
  var cfg;
  try { cfg = JSON.parse(holder.getAttribute("data-tour-config")); } catch (e) { return; }
  if (!cfg || !cfg.steps) return;

  var AUTOSTART_DELAY_MS = 700;
  var STAGE_PAD_PX = 6;
  var STAGE_RADIUS_PX = 10;
  var running = false;
  var spans = [];

  function isVisible(el) {
    if (!el || !el.getClientRects().length) return false;
    var style = window.getComputedStyle(el);
    return style.visibility !== "hidden" && style.display !== "none";
  }

  function firstVisible(name) {
    var all = document.querySelectorAll('[data-tour="' + name + '"]');
    for (var i = 0; i < all.length; i++) if (isVisible(all[i])) return all[i];
    return null;
  }

  // Группа пунктов: одна невидимая рамка по их общему прямоугольнику.
  function groupSpan(group) {
    var nodes = Array.prototype.filter.call(
      document.querySelectorAll('[data-tour-group="' + group + '"]'), isVisible);
    if (!nodes.length) return null;
    var box = nodes.reduce(function (acc, node) {
      var r = node.getBoundingClientRect();
      return {
        left: Math.min(acc.left, r.left), top: Math.min(acc.top, r.top),
        right: Math.max(acc.right, r.right), bottom: Math.max(acc.bottom, r.bottom),
      };
    }, { left: Infinity, top: Infinity, right: -Infinity, bottom: -Infinity });
    var span = document.createElement("div");
    span.className = "tour-span";
    span.style.left = box.left + "px";
    span.style.top = box.top + "px";
    span.style.width = (box.right - box.left) + "px";
    span.style.height = (box.bottom - box.top) + "px";
    document.body.appendChild(span);
    spans.push(span);
    return span;
  }

  function resolve(name) {
    if (name.indexOf("group-") === 0) return groupSpan(name.slice(6));
    return firstVisible(name);
  }

  // Куда ставить окно: рядом с левой панелью — справа от неё, внизу экрана — над, иначе под.
  function sideFor(el) {
    var r = el.getBoundingClientRect();
    if (r.right < window.innerWidth * 0.4 && r.top < window.innerHeight) return "right";
    return r.top > window.innerHeight * 0.55 ? "top" : "bottom";
  }

  function build() {
    var out = [];
    cfg.steps.forEach(function (s) {
      var popover = { title: s.title, description: s.text };
      if (!s.targets.length) { out.push({ popover: popover }); return; }
      for (var i = 0; i < s.targets.length; i++) {
        var el = resolve(s.targets[i]);
        if (el) {
          popover.side = sideFor(el);
          out.push({ element: el, popover: popover });
          return;
        }
      }
    });
    return out;
  }

  function cleanup() {
    spans.forEach(function (n) { n.remove(); });
    spans = [];
    running = false;
  }

  function loadLib(done) {
    if (window.driver && window.driver.js) { done(); return; }
    var link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = cfg.lib.css;
    document.head.appendChild(link);
    var tourLink = document.createElement("link");
    tourLink.rel = "stylesheet";
    tourLink.href = cfg.lib.tourCss;
    document.head.appendChild(tourLink);
    var script = document.createElement("script");
    script.src = cfg.lib.js;
    script.onload = done;
    script.onerror = function () { running = false; };
    document.head.appendChild(script);
  }

  function markShown() {
    var body = new FormData();
    body.append("tour", "1");
    fetch(cfg.doneUrl, {
      method: "POST", body: body, credentials: "same-origin",
      headers: { "X-Requested-With": "fetch" },
    }).catch(function () { /* не отметилось — тур откроется ещё раз, не страшно */ });
  }

  function closeAccountMenu() {
    var menu = document.getElementById("acct-menu");
    if (menu) menu.hidden = true;
  }

  function start(auto) {
    if (running) return;
    running = true;
    closeAccountMenu();
    window.scrollTo(0, 0);
    loadLib(function () {
      var steps = build();
      if (steps.length < 2) { cleanup(); return; }
      var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      var tour = window.driver.js.driver({
        steps: steps,
        showProgress: true,
        progressText: cfg.ui.progress,
        nextBtnText: cfg.ui.next,
        prevBtnText: cfg.ui.prev,
        doneBtnText: cfg.ui.done,
        closeBtnLabel: cfg.ui.close,
        popoverClass: "decimus-tour",
        animate: !reduce,
        smoothScroll: false,
        stagePadding: STAGE_PAD_PX,
        stageRadius: STAGE_RADIUS_PX,
        overlayOpacity: 0.55,
        onDestroyed: cleanup,
      });
      if (auto) markShown();
      tour.drive();
    });
  }

  document.addEventListener("click", function (e) {
    var button = e.target.closest && e.target.closest("[data-tour-start]");
    if (!button) return;
    e.preventDefault();
    start(false);
  });

  document.querySelectorAll("[data-tour-start]").forEach(function (b) { b.hidden = false; });
  if (cfg.autostart) window.setTimeout(function () { start(true); }, AUTOSTART_DELAY_MS);
})();
