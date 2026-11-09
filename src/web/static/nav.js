// Переход между разделами без перезагрузки страницы (владелец 30.09.2026:
// «при переключении вкладок постоянно обновляется страница»). Приём тот же,
// что у панели «Методики»: ссылка запрашивается фоном, а на странице
// меняется только то, что зависит от раздела — содержимое, отметка раздела в
// панелях, язык и поиск. Панель, тема и прокрутка панели остаются на месте.
//
// Не загрузился скрипт, ответ не 200, сервер увёл на вход — обычный переход:
// ссылки остаются ссылками.
//
// Каждый переход между разделами — подмена, перезагрузка остаётся только для
// экрана со скриптом в `<head>` без метки `data-swap-safe` (см. ниже).
//
// Подмена не только для левой панели (владелец 09.11.2026: «страница прям
// обновляется вместо плавного обновления»): так же идёт любая ссылка внутри
// `main.shell__main` (страна и месяц «Качества», заголовок столбца, период,
// вкладка администрирования, страница списка), отправка GET-формы отбора
// и выбор в `select[data-pick-nav]` (`window.decimusNavigate`, его зовёт
// `pick.js`). Слушатели стоят на `window`: он идёт ПОСЛЕ слушателей документа,
// поэтому клик, который экран уже взял себе (`split.js`, `country.js`,
// `decimus-rt.js`, `methodology.js`) и погасил `preventDefault`, сюда не доходит.
// Не подменяется: клик с модификатором, `target`, `download`, `rel=external`,
// чужой адрес, якорь на этой же странице, файл по расширению, ссылка и форма
// с `data-no-swap` (явный выход), POST-форма. Ответ не HTML, увод, страница без
// `main.shell__main` — обычный переход.
// Внутри экрана (путь не меняется) прокрутка страницы и колонок выбора
// остаётся на месте, запись истории помечается `page`, и шаг «назад» по ним
// тоже подмена; на другой экран страница прокручивается наверх.
//
// Скрипты экрана (`<script>` внутри `<main>`, сейчас это `methodology.js`)
// грузятся один раз. При повторном приходе на экран скрипт не запускается
// заново — иначе его клавиши сработали бы дважды, — а получает событие
// `decimus:page` и заново находит свои элементы. Перед уходом с экрана
// скрипт может отменить переход событием `decimus:leave` (незаписанная правка).
(function () {
  "use strict";
  if (!window.fetch || !window.DOMParser || !history.pushState) return;

  var LINKS = ".sidenav__list a, .sidenav__gear, .sidenav__brand, .mbar__brand, .tabbar a";
  var PAGE_LINKS = LINKS + ", main.shell__main a[href]";
  // Файлы открываются обычным переходом: подменять там нечего.
  var FILE_URL = /\.(pdf|xlsx?|csv|docx?|zip|json|txt|png|jpe?g|gif|svg|webp)$/i;
  // Колонки, у которых при подмене внутри экрана остаётся своя прокрутка.
  var KEEP_SCROLL = ".pk-rail, .split__list";
  var root = document.documentElement;
  // Скрипты экрана, уже выполненные на этой странице. Список, а не поиск
  // тега: тег уходит вместе со старым `<main>`, а скрипт остаётся в памяти.
  var loaded = {};
  // A slower response must not undo the section selected more recently.
  var navigation = 0;
  function remember() { root.dataset.navPath = location.pathname; }
  function storeRailScroll() {
    var rail = document.querySelector(".sidenav__list");
    try { if (rail) sessionStorage.setItem("decimus-nav-scroll", String(rail.scrollTop)); } catch (_) {}
  }
  window.addEventListener("pagehide", storeRailScroll);

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

  // Скрипты экрана в `<head>` (блок `head`: `split.js`, `proofread.js`, `country.js`,
  // `decimus-rt.js`…) раньше искали свои элементы один раз при загрузке, а `<head>`
  // при переходе не меняется: экран приходил без них, и строки, отборы, кнопки
  // молчали до перезагрузки (#664). Теперь скрипт, который сам подключается
  // заново на событие `decimus:navigation` (и вешает слушатели документа один раз),
  // помечается в шаблоне `data-swap-safe`: его подгружает `loadHeadScripts`, а переход
  // остаётся подменой. Скрипт без метки — по-прежнему обычный переход.
  // Скрипты оболочки (`data-shell` в `base.html`) общие для всех экранов и работают
  // через события документа — они переход не ломают.
  function hasPageHeadScripts(doc) {
    return doc.querySelectorAll("head script[src]:not([data-shell]):not([data-swap-safe])").length > 0;
  }
  function loadHeadScripts(doc) {
    doc.querySelectorAll("head script[src]:not([data-shell])").forEach(function (old) {
      var src = old.getAttribute("src");
      if (loaded[src]) return;
      loaded[src] = true;
      var s = document.createElement("script");
      s.src = src;
      document.body.appendChild(s);
    });
  }

  function apply(doc, url, push) {
    var fresh = doc.querySelector("main.shell__main");
    var here = document.querySelector("main.shell__main");
    if (!fresh || !here) return false;
    var target = new URL(url, location.href);
    var inPage = target.pathname === root.dataset.navPath;
    var pageScroll = window.scrollY;
    var columns = [];
    if (inPage) {
      document.querySelectorAll(KEEP_SCROLL).forEach(function (node, i) { columns[i] = node.scrollTop; });
    }
    var known = loadScripts(fresh);
    here.replaceWith(fresh);
    loadHeadScripts(doc);
    var oldList = document.querySelector(".sidenav__list");
    var menuScroll = oldList ? oldList.scrollTop : 0;
    sameAll(doc, ".sidenav__list");
    var newList = document.querySelector(".sidenav__list");
    if (newList) newList.scrollTop = menuScroll;
    sameAll(doc, ".sidenav__gear");
    sameAll(doc, ".tabbar");
    sameAll(doc, ".sidenav__search");
    sameAll(doc, "[data-bell]");
    sameAll(doc, "form.langpill");
    document.title = doc.title;
    if (push) {
      if (inPage && !(history.state && history.state.page)) {
        history.replaceState(Object.assign({}, history.state, { page: true }), "");
      }
      history.pushState({ nav: true, page: inPage }, "", url);
    }
    if (inPage) {
      document.querySelectorAll(KEEP_SCROLL).forEach(function (node, i) {
        if (columns[i] !== undefined) node.scrollTop = columns[i];
      });
    }
    var anchor = target.hash && document.getElementById(decodeURIComponent(target.hash.slice(1)));
    if (anchor) anchor.scrollIntoView();
    else window.scrollTo(0, inPage ? pageScroll : 0);
    remember();
    document.dispatchEvent(new Event("decimus:navigation"));
    if (known) document.dispatchEvent(new Event("decimus:page"));
    return true;
  }

  function go(url, push) {
    var current = ++navigation;
    return fetch(url, { credentials: "same-origin", headers: { "X-Requested-With": "fetch" } })
      .then(function (r) {
        if (!r.ok || r.redirected) throw new Error("status " + r.status);
        if (!/html/i.test(r.headers.get("content-type") || "")) throw new Error("not html");
        return r.text();
      })
      .then(function (html) {
        if (current !== navigation) return null;
        var doc = new DOMParser().parseFromString(html, "text/html");
        if (hasPageHeadScripts(doc)) throw new Error("head scripts");
        return ensureStyles(doc).then(function () { return doc; });
      })
      .then(function (doc) {
        if (!doc || current !== navigation) return;
        var swap = function () {
          if (current !== navigation) return;
          if (!apply(doc, url, push)) throw new Error("layout");
        };
        if (document.startViewTransition) {
          var transition = document.startViewTransition(swap);
          // Skipping an animation is harmless; a failed DOM update still falls back.
          transition.ready.catch(function () {});
          transition.finished.catch(function () {});
          return transition.updateCallbackDone;
        }
        swap();
      })
      .catch(function () {
        if (current === navigation) window.location.assign(url);
      });
  }

  // Адрес, который можно подменить (тот же сайт, не файл, не якорь на этой же странице).
  function swappable(url) {
    if (url.origin !== location.origin || FILE_URL.test(url.pathname)) return false;
    return !(url.hash && url.pathname === location.pathname && url.search === location.search);
  }

  // Общий вход: уход с экрана может отменить сам экран (`decimus:leave`).
  function open(url) {
    var leave = new Event("decimus:leave", { cancelable: true });
    if (!document.dispatchEvent(leave)) return;
    go(url.href, url.href !== location.href);
  }
  // Для скриптов, которым нужен переход «как по ссылке» (`pick.js`); false — не подмена.
  window.decimusNavigate = function (href) {
    var url = new URL(href, location.href);
    if (!swappable(url)) return false;
    open(url);
    return true;
  };

  window.addEventListener("click", function (event) {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    var link = event.target.closest && event.target.closest(PAGE_LINKS);
    if (!link || !link.href || (link.target && link.target !== "_self")) return;
    if (link.hasAttribute("download") || link.hasAttribute("data-no-swap")) return;
    if (link.getAttribute("aria-disabled") === "true" || /\bexternal\b/.test(link.getAttribute("rel") || "")) return;
    // Пункты подменю «Рейтингов» на странице раздела ведёт `decimus-rt.js` (плавная замена).
    if (link.hasAttribute("data-rt-nav") && document.querySelector(".rt[data-rt-section]")) return;
    var url = new URL(link.href, location.href);
    if (!swappable(url)) return;
    event.preventDefault();
    open(url);
  });

  // Форма отбора (GET) в содержимом экрана: адрес собирается из её полей так же,
  // как это сделал бы браузер. POST и `method=dialog` не трогаются.
  window.addEventListener("submit", function (event) {
    var form = event.target;
    if (event.defaultPrevented || !form.closest || !form.closest("main.shell__main")) return;
    var by = event.submitter || null;
    function own(name) { return (by && by.getAttribute("form" + name)) || form.getAttribute(name) || ""; }
    if ((own("method") || "get").toLowerCase() !== "get") return;
    if (form.hasAttribute("data-no-swap") || (by && by.hasAttribute("data-no-swap"))) return;
    var tgt = own("target");
    if (tgt && tgt !== "_self") return;
    var url = new URL(own("action") || location.href, location.href);
    var data = window.FormData ? new FormData(form) : null;
    if (!data) return;
    var params = new URLSearchParams();
    data.forEach(function (value, name) { if (typeof value === "string") params.append(name, value); });
    if (by && by.name && by.tagName === "BUTTON" && !params.has(by.name)) params.append(by.name, by.value);
    url.search = params.toString();
    url.hash = "";
    if (!swappable(url)) return;
    event.preventDefault();
    open(url);
  });

  // Назад и вперёд между разделами. Шаги внутри одного экрана (панель
  // «Методики» меняет только параметры адреса) — дело самого экрана; шаги по
  // записям, которые оставила подмена внутри экрана (`state.page`), ведёт `nav.js`.
  window.addEventListener("popstate", function (event) {
    ++navigation;
    if (location.pathname === root.dataset.navPath) {
      // Открытая панель справа ведёт `split.js`: закроет её и приведёт список к адресу.
      if (event.state && event.state.page && !document.querySelector("[data-drawer]")) go(location.href, false);
      return;
    }
    // Шаги внутри «Рейтингов» ведёт `decimus-rt.js`, он на странице раздела уже работает.
    if (document.querySelector(".rt[data-rt-section]") && /^\/ratings(\/|$)/.test(location.pathname)) return;
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
    document.querySelectorAll("head script[src]:not([data-shell]), main.shell__main script[src]").forEach(function (s) {
      loaded[s.getAttribute("src")] = true;
    });
    try {
      var rail = document.querySelector(".sidenav__list");
      var scroll = Number(sessionStorage.getItem("decimus-nav-scroll"));
      if (rail && Number.isFinite(scroll)) rail.scrollTop = scroll;
    } catch (_) {}
    remember();
  });
})();
