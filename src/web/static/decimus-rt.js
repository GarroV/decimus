// Разделы «Рейтингов» (D660). Что делает скрипт:
//  1. Переходы без перезагрузки: щелчок по пункту подменю, по срезу, стрелкам и выбору
//     периода, отправка календаря «с — по» — `fetch` того же адреса, замена содержимого
//     раздела и подсветки подменю, `history.pushState`, `popstate`. Содержимое плавно
//     тускнеет на время запроса, страница не мигает целиком. Не получилось — обычный
//     переход по ссылке. БЕЗ СКРИПТА всё это — обычные ссылки и форма.
//  2. Отбор раздела применяется сразу (D357): сменил девелопера или страну — пересчёт
//     без кнопки; под <noscript> остаётся кнопка «Показать».
//  3. Фильтр по странам внутри блока и хард-нарушения столбцами с «Показать ещё».
//  4. «Агрегаторы»: страна раскрывается пиццериями (без скрипта — ссылка `?country=`).
(function () {
  "use strict";

  // ── Фильтр по странам и хард-нарушения: настраиваются заново после каждой замены ──
  var COLUMN = 10;
  var WIDE = window.matchMedia("(min-width: 720px)");
  function columnsPerPage() { return WIDE.matches ? 2 : 1; }

  function setUpHard(box) {
    var list = box.querySelector("[data-rt-hard-list]");
    if (!list) return;
    var rows = Array.prototype.slice.call(list.querySelectorAll(".rt-hard__row"));
    var label = list.getAttribute("data-label");
    // На узком экране столбец один, и «Показать ещё» нужна уже при 11 строках,
    // хотя сервер рисует кнопку только за 20: недостающую заводим здесь.
    var more = box.querySelector("[data-rt-more]");
    if (!more) {
      more = document.createElement("button");
      more.type = "button";
      more.className = "btn btn--sm rt-hard__more";
      more.hidden = true;
      list.insertAdjacentElement("afterend", more);
    }
    var state = { code: "", shown: columnsPerPage() };
    function render() {
      var fit = rows.filter(function (row) {
        return state.code === "" || row.getAttribute("data-country") === state.code;
      });
      list.textContent = "";
      for (var at = 0, index = 0; at < fit.length; at += COLUMN, index += 1) {
        var column = document.createElement("ol");
        column.className = "rt-hard__col";
        column.start = at + 1;
        column.hidden = index >= state.shown;
        fit.slice(at, at + COLUMN).forEach(function (row) { column.appendChild(row); });
        list.appendChild(column);
      }
      var left = fit.length - state.shown * COLUMN;
      more.hidden = left <= 0;
      more.textContent = label.replace("{n}", String(Math.max(left, 0)));
    }
    more.addEventListener("click", function () {
      state.shown += columnsPerPage();
      render();
    });
    box.rtHard = {
      filter: function (code) { state.code = code; state.shown = columnsPerPage(); render(); }
    };
    render();
  }

  function setUp(root) {
    root.querySelectorAll(".rt-filter").forEach(function (bar) { bar.hidden = false; });
    root.querySelectorAll("[data-rt-hard]").forEach(setUpHard);
  }

  // ── Отбор ───────────────────────────────────────────────────────────────────────
  document.addEventListener("change", function (event) {
    var form = event.target.closest && event.target.closest("form[data-rt-auto]");
    if (form && event.target.tagName === "SELECT" && !event.target.hasAttribute("data-pick-nav")) {
      if (form.requestSubmit) form.requestSubmit(); else form.submit();
    }
  });

  document.addEventListener("change", function (event) {
    var select = event.target.closest && event.target.closest(".rt-filter select");
    if (!select) return;
    var code = select.value;
    var hardBox = select.closest("[data-rt-hard]");
    if (hardBox) { hardBox.rtHard.filter(code); return; }
    var block = select.closest("[data-rt-filtered]");
    block.querySelectorAll("tr[data-country]").forEach(function (row) {
      row.hidden = code !== "" && row.getAttribute("data-country") !== code;
    });
  });

  // ── «Агрегаторы»: страна раскрывается пиццериями ────────────────────────────────
  document.addEventListener("click", function (event) {
    var row = event.target.closest && event.target.closest(".rt-group__row");
    if (!row || event.defaultPrevented) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey) return;
    event.preventDefault();
    var group = row.closest(".rt-group");
    var open = group.classList.toggle("is-open");
    var toggle = row.querySelector("[data-rt-country]");
    if (toggle) toggle.setAttribute("aria-expanded", open ? "true" : "false");
  });

  // ── Переходы без перезагрузки ───────────────────────────────────────────────────
  function page() { return document.querySelector(".rt[data-rt-section]"); }
  var ticket = 0;

  function ours(url) {
    return url.origin === window.location.origin &&
      (url.pathname === "/ratings" || url.pathname.indexOf("/ratings/") === 0);
  }

  function swap(html, finalUrl) {
    var doc = new DOMParser().parseFromString(html, "text/html");
    var next = doc.querySelector(".rt[data-rt-section]");
    var current = page();
    if (!next || !current) return false;
    var sub = doc.querySelector("[data-rt-subnav]");
    var here = document.querySelector("[data-rt-subnav]");
    if (sub && here) here.replaceWith(sub);
    next.classList.add("is-loading");
    current.replaceWith(next);
    setUp(next);
    document.title = doc.title;
    // Одна перерисовка со сниженной непрозрачностью — и плавное проявление, а не вспышка.
    window.requestAnimationFrame(function () {
      window.requestAnimationFrame(function () { next.classList.remove("is-loading"); });
    });
    return true;
  }

  function go(target, push) {
    var url = new URL(target, window.location.href);
    if (!ours(url)) { window.location.href = url.href; return; }
    var mine = ++ticket;
    var current = page();
    var sameSection = current && url.pathname.replace(/\/$/, "") === window.location.pathname.replace(/\/$/, "");
    if (current) current.classList.add("is-loading");
    fetch(url.href, { credentials: "same-origin", headers: { "X-Requested-With": "decimus-rt" } })
      .then(function (res) {
        if (!res.ok) throw new Error("status " + res.status);
        return res.text().then(function (text) { return { text: text, url: res.url }; });
      })
      .then(function (got) {
        if (mine !== ticket) return;
        var landed = new URL(got.url);
        if (!ours(landed) || !swap(got.text, landed)) throw new Error("not a ratings page");
        if (push) window.history.pushState({ rt: 1 }, "", landed.pathname + landed.search);
        if (!sameSection) window.scrollTo(0, 0);
      })
      .catch(function () {
        if (mine === ticket) window.location.href = url.href;
      });
  }

  function plainClick(event) {
    return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
  }

  document.addEventListener("click", function (event) {
    var link = event.target.closest && event.target.closest("a[href]");
    if (!link || event.defaultPrevented || !plainClick(event)) return;
    if (link.target && link.target !== "_self") return;
    if (!link.hasAttribute("data-rt-nav") &&
        !(link.classList.contains("rt-cal__arrow") && link.closest(".rt-bar"))) return;
    event.preventDefault();
    go(link.href, true);
  });

  // Выбор в списке: срез и период (`.rt-bar`) и раздел на телефоне (`data-rt-nav`).
  // Обработчик у `document` в фазе захвата идёт раньше общего `pick.js`, который
  // сделал бы обычный переход, — поэтому ловим первыми и не пускаем дальше.
  document.addEventListener("change", function (event) {
    var select = event.target;
    if (!select.matches || !select.matches("select[data-pick-nav]") || !select.value) return;
    if (!select.closest(".rt") || select.hasAttribute("data-drawer-open")) return;
    event.stopImmediatePropagation();
    go(select.value, true);
  }, true);

  // Календарь «с — по» и выбор значения среза — обычная форма отбора: собираем адрес сами.
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.matches || !form.matches("form.rt-bar[data-rt-auto]") || event.defaultPrevented) return;
    event.preventDefault();
    var url = new URL(form.getAttribute("action") || window.location.pathname, window.location.href);
    new FormData(form).forEach(function (value, name) {
      if (typeof value === "string" && value !== "") url.searchParams.set(name, value);
    });
    go(url.href, true);
  });

  window.addEventListener("popstate", function () {
    if (page() && ours(new URL(window.location.href))) go(window.location.href, false);
  });

  // Первая запись истории помечена — к ней можно вернуться кнопкой «Назад» без перезагрузки.
  if (page()) window.history.replaceState({ rt: 1 }, "", window.location.pathname + window.location.search);
  setUp(document);
})();
