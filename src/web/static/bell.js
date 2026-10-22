// Колокольчик уведомлений (#1129, D604, D614): всплывающее окно со списком, как меню
// учётки (`shell.js`). Страница рисует только кнопку и красную точку; список
// приходит фрагментом `GET /settings/notifications` при каждом открытии (новое
// появляется между открытиями). Клик по уведомлению отмечает его прочитанным и ведёт
// по адресу; без скрипта кнопка ничего не открывает, а точки и пункты меню работают.
// Слушатели висят на документе: переход между разделами (`nav.js`) подменяет части
// страницы, и привязанные к узлам слушатели пропали бы.
(function () {
  "use strict";
  var MENU_GAP = 6;
  var bellTrigger = null;

  function menuEl() { return document.getElementById("notif-menu"); }
  function bells() { return document.querySelectorAll("[data-bell]"); }
  function box(menu) { return menu.querySelector("[data-src]"); }

  function focusables(menu) {
    return Array.prototype.filter.call(
      menu.querySelectorAll("a[href], button:not([disabled])"),
      function (el) { return el.offsetParent !== null; }
    );
  }

  function place(menu, trigger) {
    var rect = trigger.getBoundingClientRect();
    var up = trigger.dataset.place === "up";
    menu.classList.toggle("acct-menu--up", up);
    menu.classList.toggle("acct-menu--down", !up);
    if (up) {
      menu.style.setProperty("--acct-x", Math.max(8, rect.left) + "px");
      menu.style.setProperty("--acct-y", Math.round(window.innerHeight - rect.top + MENU_GAP) + "px");
    } else {
      menu.style.setProperty("--acct-y", Math.round(rect.bottom + MENU_GAP) + "px");
    }
  }

  function setDots(unread) {
    document.querySelectorAll(".bell__dot").forEach(function (d) { d.hidden = !unread; });
  }

  // Сессия кончилась: заслон уводит на вход, fetch проходит редирект молча и отдал бы
  // целую страницу внутрь окна. Уходим туда же всей вкладкой (как `loadConnections`).
  function load(menu) {
    var body = box(menu);
    if (!body || !window.fetch) return;
    fetch(body.dataset.src, { credentials: "same-origin", headers: { "X-Requested-With": "fetch" } })
      .then(function (r) {
        if (r.redirected) { window.location.assign(r.url); return null; }
        if (!r.ok) throw new Error("status " + r.status);
        return r.text();
      })
      .then(function (html) {
        if (html === null) return;
        body.innerHTML = html;
        var first = focusables(menu)[0];
        if (first && !menu.hidden) first.focus();
      })
      .catch(function () { body.textContent = body.dataset.failed || ""; });
  }

  function open(trigger) {
    var menu = menuEl();
    if (!menu) return;
    bellTrigger = trigger;
    place(menu, trigger);
    menu.hidden = false;
    bells().forEach(function (b) { b.setAttribute("aria-expanded", String(b === trigger)); });
    menu.focus();
    load(menu);
  }

  function close(returnFocus) {
    var menu = menuEl();
    if (!menu || menu.hidden) return;
    menu.hidden = true;
    bells().forEach(function (b) { b.setAttribute("aria-expanded", "false"); });
    if (returnFocus && bellTrigger) bellTrigger.focus();
    bellTrigger = null;
  }

  // Отметка уходит фоном и не держит переход: страница с тем же адресом отметит строку
  // сама, а оборвавшийся запрос не должен запирать человека в окне.
  function post(url) {
    if (!window.fetch) return Promise.resolve();
    return fetch(url, { method: "POST", credentials: "same-origin", keepalive: true,
      headers: { "X-Requested-With": "fetch" } }).catch(function () { /* страница отметит сама */ });
  }

  document.addEventListener("click", function (e) {
    var menu = menuEl();
    if (!menu) return;
    var trigger = e.target.closest && e.target.closest("[data-bell]");
    if (trigger) {
      e.preventDefault();
      if (!menu.hidden && bellTrigger === trigger) close(true);
      else open(trigger);
      return;
    }
    if (menu.hidden) return;
    var row = e.target.closest && e.target.closest("[data-read-url]");
    if (row && menu.contains(row)) {
      e.preventDefault();
      var href = row.getAttribute("href");
      post(row.dataset.readUrl).then(function () { window.location.assign(href); });
      return;
    }
    var all = e.target.closest && e.target.closest("[data-read-all-url]");
    if (all && menu.contains(all)) {
      e.preventDefault();
      post(all.dataset.readAllUrl).then(function () {
        menu.querySelectorAll(".notif-row.is-unread").forEach(function (r) { r.classList.remove("is-unread"); });
        all.hidden = true;
        setDots(false);
      });
      return;
    }
    if (!menu.contains(e.target)) close(false);
  });

  document.addEventListener("keydown", function (e) {
    var menu = menuEl();
    if (!menu || menu.hidden) return;
    if (e.key === "Escape") {
      e.preventDefault();
      close(true);
    } else if (e.key === "Tab") {
      // Фокус не уходит за окно: на краях он замыкается, а не теряется.
      var items = focusables(menu);
      if (!items.length) { e.preventDefault(); return; }
      var first = items[0], last = items[items.length - 1];
      if (e.shiftKey && (document.activeElement === first || document.activeElement === menu)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  });

  var lastWidth = window.innerWidth;
  window.addEventListener("resize", function () {
    if (window.innerWidth === lastWidth) return;
    lastWidth = window.innerWidth;
    close(false);
  });
  document.addEventListener("decimus:leave", function () { close(false); });
})();
