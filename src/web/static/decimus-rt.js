// Отбор раздела «Рейтинги» применяется сразу (D357): сменил девелопера или
// страну — страница перестраивается без кнопки. Срез и период — ссылки, им
// скрипт не нужен. Не загрузился — под <noscript> остаётся кнопка «Показать».
(function () {
  "use strict";
  document.addEventListener("change", function (event) {
    var form = event.target.closest && event.target.closest("form[data-rt-auto]");
    if (form && event.target.tagName === "SELECT" && !event.target.hasAttribute("data-pick-nav")) form.submit();
  });

  // Подсказка свечи — сразу при наведении или фокусе (D385): системная по
  // `title` всплывает через секунду, поэтому у точки его нет — текст для экранных чтецов в `aria-label`.
  var tip = null;
  function show(node) {
    tip = tip || document.querySelector(".rt-tip");
    if (!tip) return;
    tip.textContent = node.getAttribute("data-tip");
    tip.hidden = false;
    var box = node.getBoundingClientRect();
    var left = Math.min(box.left, window.innerWidth - tip.offsetWidth - 8);
    var top = box.top - tip.offsetHeight - 8;
    tip.style.left = Math.max(8, left) + "px";
    tip.style.top = (top < 8 ? box.bottom + 8 : top) + "px";
  }
  function hide() { if (tip) tip.hidden = true; }
  function candle(event) {
    return event.target.closest && event.target.closest("[data-tip]");
  }
  ["mouseover", "focusin"].forEach(function (type) {
    document.addEventListener(type, function (event) {
      var node = candle(event);
      if (node) show(node);
    });
  });
  ["mouseout", "focusout"].forEach(function (type) {
    document.addEventListener(type, function (event) { if (candle(event)) hide(); });
  });
  document.addEventListener("scroll", hide, true);

  // Фильтр по странам в блоке (зона риска, хард-нарушения): прячет строки чужих
  // стран только в своём блоке. Без скрипта фильтр скрыт — видны все строки.
  document.querySelectorAll(".rt-filter").forEach(function (bar) { bar.hidden = false; });
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

  // Хард-нарушения (D585): столбцы по десять строк, на широком экране по два
  // столбца, на узком по одному; «Показать ещё» открывает следующие столбцы.
  // Сервер уже разложил строки так же — скрипт раскладывает заново под выбранную
  // страну и прячет то, что дальше первой страницы.
  var COLUMN = 10;
  var WIDE = window.matchMedia("(min-width: 720px)");
  function columnsPerPage() { return WIDE.matches ? 2 : 1; }
  document.querySelectorAll("[data-rt-hard]").forEach(function (box) {
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
  });

  // Плитки (D585): раскрываются на месте, открыта одна; открытая — в адресе
  // (`?open=`), чтобы ссылка и перезагрузка её сохраняли. Остальные плитки
  // переезжают плавно (FLIP); раскрывающаяся — вырастает из своего прежнего места.
  var grid = document.querySelector(".rt-tiles");
  if (!grid) return;
  var still = window.matchMedia("(prefers-reduced-motion: reduce)");
  var cards = Array.prototype.slice.call(grid.querySelectorAll(".rt-tile"));
  function openCard() { return grid.querySelector(".rt-tile.is-open"); }
  function swap(card, on) {
    var face = card.querySelector(".rt-tile__face");
    card.classList.toggle("is-open", on);
    face.setAttribute("aria-expanded", on ? "true" : "false");
    face.value = on ? "none" : card.getAttribute("data-tile");
    card.querySelector(".rt-tile__body").hidden = !on;
    var text = card.querySelector(".rt-tile__more-text");
    var next = text.getAttribute(on ? "data-close" : "data-open");
    if (next) text.textContent = next;
  }
  function remember(key) {
    var url = new URL(window.location.href);
    url.searchParams.set("open", key || "none");
    window.history.replaceState(null, "", url);
    document.querySelectorAll('.rt-bar a[href*="open="]').forEach(function (link) {
      var to = new URL(link.href, window.location.href);
      to.searchParams.set("open", key || "none");
      link.setAttribute("href", to.pathname + to.search);
    });
  }
  function glide(before, target) {
    cards.forEach(function (card) {
      var was = before.get(card);
      var now = card.getBoundingClientRect();
      var dx = was.left - now.left;
      var dy = was.top - now.top;
      if (card === target) {
        var grew = dx >= 0 && dy >= 0 && now.right >= was.right && now.bottom >= was.bottom;
        if (!grew) return;
        var from = "inset(" + dy + "px " + (now.right - was.right) + "px " +
          (now.bottom - was.bottom) + "px " + dx + "px round 12px)";
        card.animate({ clipPath: [from, "inset(0 0 0 0 round 12px)"] },
          { duration: 280, easing: "cubic-bezier(.2,.7,.2,1)" });
      } else if (dx || dy) {
        card.animate({ transform: ["translate(" + dx + "px," + dy + "px)", "none"] },
          { duration: 280, easing: "cubic-bezier(.2,.7,.2,1)" });
      }
    });
  }
  function toggle(card) {
    var key = card.classList.contains("is-open") ? null : card.getAttribute("data-tile");
    var before = new Map();
    cards.forEach(function (c) { before.set(c, c.getBoundingClientRect()); });
    cards.forEach(function (c) { swap(c, c.getAttribute("data-tile") === key); });
    remember(key);
    if (still.matches) return;
    glide(before, key ? grid.querySelector('[data-tile="' + key + '"]') : null);
    if (key) {
      var top = grid.querySelector('[data-tile="' + key + '"]').getBoundingClientRect().top;
      if (top < 0 || top > window.innerHeight * 0.7) {
        grid.querySelector('[data-tile="' + key + '"]').scrollIntoView({ block: "start", behavior: "smooth" });
      }
    }
  }
  grid.addEventListener("click", function (event) {
    var face = event.target.closest && event.target.closest(".rt-tile__face");
    if (!face) return;
    event.preventDefault();
    toggle(face.closest(".rt-tile"));
  });
  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape" || event.defaultPrevented) return;
    if (document.querySelector(".rt-cal__pick[open]")) return;
    var card = openCard();
    if (!card) return;
    toggle(card);
    card.querySelector(".rt-tile__face").focus();
  });
})();
