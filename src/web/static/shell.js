// Оболочка админки: ⌘K в поиск левой панели, переключатель темы (эталон —
// Swarm Brain) и меню учётки поверх страницы (D468). Страница работает и без
// этого файла: поиск остаётся обычной формой, тема — системной, а блок учётки —
// ссылкой в «Настройки».
(function () {
  "use strict";
  var STORE = "decimus-theme";

  document.addEventListener("keydown", function (e) {
    var field = document.querySelector("[data-hotkey='k']");
    if (!field) return;
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      field.focus();
      field.select();
    } else if (e.key === "Escape" && document.activeElement === field) {
      field.value = "";
      field.blur();
    }
  });

  function stored() {
    try { return localStorage.getItem(STORE); } catch (e) { return null; }
  }

  function mark(choice) {
    document.querySelectorAll("[data-theme-value]").forEach(function (b) {
      b.setAttribute("aria-checked", String(b.dataset.themeValue === choice));
    });
  }

  function apply(choice) {
    try {
      if (choice === "system") localStorage.removeItem(STORE);
      else localStorage.setItem(STORE, choice);
    } catch (e) { /* приватный режим: выбор живёт до перезагрузки */ }
    var dark = choice === "dark" || (choice === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    mark(choice);
  }


  // ── Меню учётки (D468) ──────────────────────────────────────────────
  // Одно меню `#acct-menu` на страницу; открывают его блок учётки в панели
  // (`data-place="up"`, над блоком) и аватар в полосе телефона (`"down"`).
  // Без скрипта обе точки остаются ссылками в «Настройки»: роль кнопки и
  // aria-атрибуты ставятся здесь, а не в разметке, где они соврали бы.
  // Слушатели висят на документе: переход между разделами (`nav.js`) подменяет
  // части страницы, и привязанные к узлам слушатели пропали бы.
  var MENU_GAP = 6;
  var menuTrigger = null;
  var connectionsLoaded = false;

  function menuEl() { return document.getElementById("acct-menu"); }

  function menuTriggers() { return document.querySelectorAll("[data-acct-menu]"); }

  function enhanceTriggers() {
    var menu = menuEl();
    if (!menu) return;
    menuTriggers().forEach(function (a) {
      a.setAttribute("role", "button");
      a.setAttribute("aria-haspopup", "menu");
      a.setAttribute("aria-expanded", "false");
      a.setAttribute("aria-controls", "acct-menu");
    });
  }

  function focusables(menu) {
    return Array.prototype.filter.call(
      menu.querySelectorAll("a[href], button:not([disabled])"),
      function (el) { return el.offsetParent !== null; }
    );
  }

  // Подключения — фрагментом при первом открытии. Не загрузились — остаются
  // строки-ссылки без состояния, меню от этого не ломается.
  function loadConnections(menu) {
    if (connectionsLoaded) return;
    var box = menu.querySelector("[data-src]");
    if (!box || !window.fetch) return;
    connectionsLoaded = true;
    fetch(box.dataset.src, { credentials: "same-origin", headers: { "X-Requested-With": "fetch" } })
      .then(function (r) {
        if (!r.ok) throw new Error("status " + r.status);
        return r.text();
      })
      .then(function (html) { box.innerHTML = html; })
      .catch(function () { connectionsLoaded = false; });
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

  function openMenu(trigger) {
    var menu = menuEl();
    if (!menu) return;
    menuTrigger = trigger;
    place(menu, trigger);
    menu.hidden = false;
    menuTriggers().forEach(function (a) { a.setAttribute("aria-expanded", String(a === trigger)); });
    loadConnections(menu);
    var first = focusables(menu)[0];
    (first || menu).focus();
  }

  function closeMenu(returnFocus) {
    var menu = menuEl();
    if (!menu || menu.hidden) return;
    menu.hidden = true;
    menuTriggers().forEach(function (a) { a.setAttribute("aria-expanded", "false"); });
    if (returnFocus && menuTrigger) menuTrigger.focus();
    menuTrigger = null;
  }

  document.addEventListener("click", function (e) {
    var menu = menuEl();
    if (!menu) return;
    var trigger = e.target.closest && e.target.closest("[data-acct-menu]");
    if (trigger && trigger.getAttribute("aria-haspopup") === "menu") {
      e.preventDefault();
      if (!menu.hidden && menuTrigger === trigger) closeMenu(true);
      else openMenu(trigger);
      return;
    }
    // Клик мимо меню закрывает его; клик внутри (в том числе по ссылке) — нет.
    if (!menu.hidden && !menu.contains(e.target)) closeMenu(false);
  });

  document.addEventListener("keydown", function (e) {
    var menu = menuEl();
    if (!menu || menu.hidden) {
      // Ссылка с ролью кнопки: Пробел её не открывает сам — добавляем.
      var t = e.target;
      if (e.key === " " && t.matches && t.matches("[data-acct-menu][aria-haspopup]")) {
        e.preventDefault();
        openMenu(t);
      }
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      closeMenu(true);
    } else if (e.key === "Tab") {
      // Фокус не уходит за меню: на краях он замыкается, а не теряется.
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

  // Смена ширины сдвигает якорь; проще закрыть, чем пересчитывать. Высота не в
  // счёт: на телефоне она меняется от адресной строки при прокрутке.
  var lastWidth = window.innerWidth;
  window.addEventListener("resize", function () {
    if (window.innerWidth === lastWidth) return;
    lastWidth = window.innerWidth;
    closeMenu(false);
  });
  document.addEventListener("decimus:leave", function () { closeMenu(false); });

  document.addEventListener("DOMContentLoaded", function () {
    enhanceTriggers();
    var now = stored();
    mark(now === "light" || now === "dark" ? now : "system");
    document.querySelectorAll("[data-theme-value]").forEach(function (b) {
      b.addEventListener("click", function () { apply(b.dataset.themeValue); });
    });
  });
})();
