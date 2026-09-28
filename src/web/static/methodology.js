// Экран чек-листа (D197): панель справа поверх списка. Каждое действие — это
// уже ссылка или форма на странице; скрипт только делает их удобнее. Не
// загрузился — всё работает мышью и перезагрузкой, как без него.
//
// Что добавляет скрипт:
//  * клавиши: ↑/↓ (j/k) — соседний пункт, Esc — закрыть, «/» — к поиску;
//  * подмену панели без перезагрузки: список не прыгает к началу при каждом
//    клике по пункту, адрес меняется как при обычном переходе;
//  * выезд панели — только при открытии, листание стрелками её не дёргает;
//  * кнопка записи активна, только когда в форме есть правка, и уход из
//    панели с незаписанной правкой спрашивает подтверждения;
//  * поля формулировки и критериев растут по тексту;
//  * «набрано» под долями зон — подсказка при вводе, сумму судит движок.
(function () {
  "use strict";
  var ENTER_KEY = "mx-drawer-open";

  function layer() { return document.querySelector("[data-mx-layer]"); }
  function typing(target) {
    var tag = target && target.tagName;
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (target && target.isContentEditable);
  }
  function isOpen() { var l = layer(); return !!(l && l.classList.contains("is-open")); }
  function remember() {
    try { sessionStorage.setItem(ENTER_KEY, isOpen() ? "1" : "0"); } catch (e) { /* приватное окно */ }
  }
  function wasOpen() {
    try { return sessionStorage.getItem(ENTER_KEY) === "1"; } catch (e) { return false; }
  }

  // --- Поля панели -------------------------------------------------------
  function grow(area) { area.style.height = "auto"; area.style.height = area.scrollHeight + 2 + "px"; }
  // Имя набора и «зачем правим» — часть записи, а не правка: от них кнопка
  // не оживает и уход из панели не спрашивает.
  var RECORD_FIELDS = { note: true, version_name: true };
  function snapshot(form) {
    var data = new FormData(form);
    Object.keys(RECORD_FIELDS).forEach(function (name) { data.delete(name); });
    return new URLSearchParams(data).toString();
  }
  function dirtyForms() {
    return Array.prototype.filter.call(document.querySelectorAll("[data-mx-form]"), function (f) {
      return f.dataset.mxInitial !== undefined && snapshot(f) !== f.dataset.mxInitial;
    });
  }
  function refreshDirty() {
    var any = false;
    document.querySelectorAll("[data-mx-form]").forEach(function (form) {
      var dirty = snapshot(form) !== form.dataset.mxInitial;
      any = any || dirty;
      form.querySelectorAll("[data-mx-record] button[type=submit]").forEach(function (b) { b.disabled = !dirty; });
    });
    var mark = document.querySelector("[data-mx-dirty]");
    if (mark) mark.hidden = !any;
  }
  function recount(form) {
    var sum = form.querySelector("[data-mx-share-sum]");
    if (!sum) return;
    var total = 0, ok = true;
    form.querySelectorAll("[data-mx-share]").forEach(function (input) {
      var raw = input.value.trim().replace(",", ".");
      if (raw === "") return;
      var n = Number(raw);
      if (isNaN(n)) ok = false; else total += n;
    });
    sum.textContent = ok ? (Math.round(total * 100) / 100) + "%" : "—";
  }
  function initPanel() {
    document.querySelectorAll("[data-mx-grow]").forEach(grow);
    document.querySelectorAll("[data-mx-form]").forEach(function (form) {
      form.dataset.mxInitial = snapshot(form);
    });
    document.querySelectorAll("[data-mx-shares]").forEach(recount);
    refreshDirty();
    var current = document.querySelector(".mx-row.is-on");
    if (current && current.scrollIntoView) current.scrollIntoView({ block: "nearest" });
  }
  document.addEventListener("input", function (event) {
    if (event.target.matches && event.target.matches("[data-mx-grow]")) grow(event.target);
    var form = event.target.closest && event.target.closest("[data-mx-form]");
    if (!form) return;
    if (form.matches("[data-mx-shares]")) recount(form);
    refreshDirty();
  });
  document.addEventListener("change", function (event) {
    if (event.target.closest && event.target.closest("[data-mx-form]")) refreshDirty();
  });
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (form.dataset) delete form.dataset.mxInitial; // своя отправка — не «уход с правкой»
    remember();
  });

  function mayLeave() {
    if (!dirtyForms().length) return true;
    var l = layer();
    return window.confirm((l && l.dataset.mxLeave) || "?");
  }
  window.addEventListener("beforeunload", function (event) {
    if (dirtyForms().length) { event.preventDefault(); event.returnValue = ""; }
  });

  // --- Подмена панели ----------------------------------------------------
  function swap(html, url, push) {
    var doc = new DOMParser().parseFromString(html, "text/html");
    var fresh = doc.querySelector("[data-mx-layer]");
    var old = layer();
    if (!fresh || !old) { window.location.assign(url); return; }
    var opening = !isOpen() && fresh.classList.contains("is-open");
    old.replaceWith(fresh);
    if (opening) fresh.classList.add("is-entering");
    // Выбранная строка и кнопки шапки — из нового ответа.
    var code = new URL(url, window.location.href).searchParams.get("item");
    document.querySelectorAll(".mx-row").forEach(function (row) {
      var on = !!code && row.dataset.mxItem === code;
      row.classList.toggle("is-on", on);
      if (on) row.setAttribute("aria-current", "true"); else row.removeAttribute("aria-current");
    });
    var bar = doc.querySelector(".mx-bar__actions");
    var here = document.querySelector(".mx-bar__actions");
    if (bar && here) here.replaceWith(bar);
    if (push) history.pushState({ mx: true }, "", url);
    initPanel();
    var focus = fresh.querySelector(".mx-drawer__head .mx-icon[data-mx-close]");
    if (opening && focus) focus.focus({ preventScroll: true });
    remember();
  }
  function open(url, push) {
    return fetch(url, { credentials: "same-origin", headers: { "X-Requested-With": "fetch" } })
      .then(function (r) {
        if (!r.ok || r.redirected) throw new Error("status " + r.status);
        return r.text();
      })
      .then(function (html) { swap(html, url, push); })
      .catch(function () { window.location.assign(url); });
  }
  document.addEventListener("click", function (event) {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    var link = event.target.closest && event.target.closest("a[data-mx-open], a[data-mx-close]");
    if (!link || link.getAttribute("aria-disabled") === "true") return;
    event.preventDefault();
    if (!mayLeave()) return;
    open(link.href, true);
  });
  window.addEventListener("popstate", function () { open(window.location.href, false); });

  // --- Клавиши -----------------------------------------------------------
  function press(selector) {
    var link = document.querySelector(selector);
    if (!link) return false;
    link.click();
    return true;
  }
  document.addEventListener("keydown", function (event) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    if (typing(event.target)) {
      if (event.key === "Escape") event.target.blur();
      return;
    }
    // Открытый чип или «ещё действия» закрываются первыми: Esc снимает верхний слой.
    var top = document.querySelector("details.pick[open], details.mx-more[open]");
    if (event.key === "Escape" && top) { top.removeAttribute("open"); return; }
    var handled = false;
    if (event.key === "Escape") handled = press(".mx-drawer [data-mx-close]");
    else if (event.key === "ArrowDown" || event.key === "j") handled = press("[data-mx-next]");
    else if (event.key === "ArrowUp" || event.key === "k") handled = press("[data-mx-prev]");
    else if (event.key === "/") {
      var search = document.querySelector("[data-mx-search]");
      if (search) { search.focus(); search.select(); handled = true; }
    }
    if (handled) event.preventDefault();
  });

  // Ответ на запись формы приходит по адресу действия (`/admin/items/…`):
  // обновление страницы повторило бы запись, а меню не узнало бы раздел.
  // Адрес ставится экранный — тот же, что дала бы ссылка на эту панель.
  var canonical = layer() && layer().dataset.mxCanonical;
  if (canonical && new URL(canonical, location.href).pathname !== location.pathname) {
    history.replaceState(null, "", canonical);
  }

  // Первая загрузка: выезд — только если панель открылась из закрытого
  // состояния, а не после записи формы или обновления страницы с панелью.
  if (isOpen() && !wasOpen()) layer().classList.add("is-entering");
  initPanel();
  remember();
  window.addEventListener("pagehide", remember);
})();
