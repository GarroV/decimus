// Переход между разделами без перезагрузки страницы (владелец 30.09.2026:
// «при переключении вкладок постоянно обновляется страница»). Приём тот же,
// что у панели «Методики»: ссылка запрашивается фоном, а на странице
// меняется только то, что зависит от раздела — содержимое, отметка раздела в
// панелях, язык и поиск. Панель, тема и прокрутка панели остаются на месте.
//
// Не загрузился скрипт, ответ не 200, сервер увёл на вход — обычный переход:
// ссылки остаются ссылками.
//
// Скрипты экрана (`<script>` внутри `<main>`, сейчас это `methodology.js`)
// грузятся один раз. При повторном приходе на экран скрипт не запускается
// заново — иначе его клавиши сработали бы дважды, — а получает событие
// `decimus:page` и заново находит свои элементы. Перед уходом с экрана
// скрипт может отменить переход событием `decimus:leave` (незаписанная правка).
(function () {
  "use strict";
  if (!window.fetch || !window.DOMParser || !history.pushState) return;

  var LINKS = ".sidenav__list a, .sidenav__brand, .mbar__brand, .tabbar a";
  var root = document.documentElement;
  // Скрипты экрана, уже выполненные на этой странице. Список, а не поиск
  // тега: тег уходит вместе со старым `<main>`, а скрипт остаётся в памяти.
  var loaded = {};
  function remember() { root.dataset.navPath = location.pathname; }

  function sameAll(doc, selector) {
    var fresh = doc.querySelectorAll(selector);
    var here = document.querySelectorAll(selector);
    if (fresh.length !== here.length) return false;
    here.forEach(function (node, i) { node.replaceWith(fresh[i]); });
    return true;
  }

  function loadScripts(main) {
    var known = false;
    main.querySelectorAll("script[src]").forEach(function (old) {
      var src = old.getAttribute("src");
      old.remove();
      if (loaded[src]) { known = true; return; }
      loaded[src] = true;
      var s = document.createElement("script");
      s.src = src;
      document.body.appendChild(s);
    });
    return known;
  }

  // Стили экрана лежат в `<head>` (блок `head` шаблона), а он при переходе
  // не меняется: без этого «Главная», открытая из «Проверок», приходила без
  // своего `decimus-home.css` и рассыпалась до перезагрузки (11.10.2026).
  // Недостающие таблицы добавляются и ждутся ДО подмены, чтобы экран не
  // мигнул голым; не загрузилась за STYLE_WAIT_MS — меняем всё равно.
  var STYLE_WAIT_MS = 3000;
  function ensureStyles(doc) {
    var have = {};
    document.querySelectorAll('link[rel="stylesheet"]').forEach(function (l) {
      have[l.getAttribute("href")] = true;
    });
    var waits = [];
    doc.querySelectorAll('head link[rel="stylesheet"]').forEach(function (l) {
      var href = l.getAttribute("href");
      if (have[href]) return;
      have[href] = true;
      var link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = href;
      waits.push(new Promise(function (done) {
        link.onload = link.onerror = done;
        setTimeout(done, STYLE_WAIT_MS);
      }));
      document.head.appendChild(link);
    });
    return Promise.all(waits);
  }

  // Скрипты экрана в `<head>` (блок `head`: `split.js` реестра и «Пользователей»,
  // `decimus-rt.js` «Рейтингов») ищут свои элементы при загрузке, а `<head>`
  // при переходе не меняется: экран приходил без них, и строки, отборы,
  // кнопки молчали до перезагрузки (#664). Такой экран открывается обычным
  // переходом. Скрипты оболочки (`data-shell` в `base.html`) общие для всех
  // экранов и работают через события документа — они переход не ломают.
  function hasPageHeadScripts(doc) {
    return doc.querySelector("head script[src]:not([data-shell])") !== null;
  }

  function apply(doc, url, push) {
    var fresh = doc.querySelector("main.shell__main");
    var here = document.querySelector("main.shell__main");
    if (!fresh || !here) return false;
    var known = loadScripts(fresh);
    here.replaceWith(fresh);
    sameAll(doc, ".sidenav__list");
    sameAll(doc, ".tabbar");
    sameAll(doc, ".sidenav__search");
    sameAll(doc, "[data-bell]");
    sameAll(doc, "form.langpill");
    document.title = doc.title;
    if (push) history.pushState({ nav: true }, "", url);
    window.scrollTo(0, 0);
    remember();
    if (known) document.dispatchEvent(new Event("decimus:page"));
    return true;
  }

  function go(url, push) {
    return fetch(url, { credentials: "same-origin", headers: { "X-Requested-With": "fetch" } })
      .then(function (r) {
        if (!r.ok || r.redirected) throw new Error("status " + r.status);
        return r.text();
      })
      .then(function (html) {
        var doc = new DOMParser().parseFromString(html, "text/html");
        if (hasPageHeadScripts(doc)) throw new Error("head scripts");
        return ensureStyles(doc).then(function () { return doc; });
      })
      .then(function (doc) {
        var swap = function () { if (!apply(doc, url, push)) throw new Error("layout"); };
        if (document.startViewTransition) document.startViewTransition(swap);
        else swap();
      })
      .catch(function () { window.location.assign(url); });
  }

  document.addEventListener("click", function (event) {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    var link = event.target.closest && event.target.closest(LINKS);
    if (!link || !link.href || link.target) return;
    var url = new URL(link.href, location.href);
    if (url.origin !== location.origin) return;
    event.preventDefault();
    var leave = new Event("decimus:leave", { cancelable: true });
    if (!document.dispatchEvent(leave)) return;
    go(url.href, true);
  });

  // Назад и вперёд между разделами. Шаги внутри одного экрана (панель
  // «Методики» меняет только параметры адреса) — дело самого экрана.
  window.addEventListener("popstate", function () {
    if (location.pathname === root.dataset.navPath) return;
    go(location.href, false);
  });

  // «Ещё» нижней панели (D518) закрывается касанием мимо него и клавишей Esc —
  // как любое всплывающее меню; сам `details` умеет только открыть и закрыть
  // по своему заголовку.
  function closeMore(except) {
    document.querySelectorAll(".tabbar__more[open]").forEach(function (more) {
      if (more !== except) more.removeAttribute("open");
    });
  }
  document.addEventListener("click", function (e) {
    closeMore(e.target.closest ? e.target.closest(".tabbar__more") : null);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeMore(null);
  });

  // После скриптов экрана: они могут поправить адрес (`replaceState`).
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("main.shell__main script[src]").forEach(function (s) {
      loaded[s.getAttribute("src")] = true;
    });
    remember();
  });
})();
