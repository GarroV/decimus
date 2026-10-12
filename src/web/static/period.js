// Календарь периода (`_period.html`): маленький месяц с выбором отрезка двумя
// щелчками — начало, затем конец (порядок не важен); второй щелчок применяет.
// Образец — Swarm, `RangePicker.tsx`. Без скрипта остаётся форма с двумя
// полями даты и кнопкой «Применить» — она рабочая и сама по себе.
//
// Всё на делегировании: экран может подмениться переходом без перезагрузки
// (`nav.js`), поэтому сетка строится при раскрытии, а не при загрузке страницы.
(function () {
  "use strict";

  function iso(y, m, d) {
    return y + "-" + String(m + 1).padStart(2, "0") + "-" + String(d).padStart(2, "0");
  }
  function parse(value) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value || "");
    return m ? { y: +m[1], m: +m[2] - 1, d: +m[3] } : null;
  }

  function build(form) {
    var grid = form.querySelector("[data-pcal-grid]");
    if (!grid || form.dataset.ready) return;
    form.dataset.ready = "1";
    form.classList.add("is-js");
    grid.hidden = false;

    var months = form.dataset.months.split("|");
    var weekdays = form.dataset.weekdays.split(" ");
    var from = parse(form.dataset.from), to = parse(form.dataset.to);
    var now = new Date();
    var view = from ? { y: from.y, m: from.m } : { y: now.getFullYear(), m: now.getMonth() };
    var today = iso(now.getFullYear(), now.getMonth(), now.getDate());
    var anchor = null, hover = null;

    function el(tag, cls, text) {
      var node = document.createElement(tag);
      if (cls) node.className = cls;
      if (text !== undefined) node.textContent = text;
      return node;
    }
    function step(delta) {
      var total = view.y * 12 + view.m + delta;
      view = { y: Math.floor(total / 12), m: total % 12 };
      draw();
    }
    function apply(a, b) {
      var lo = a < b ? a : b, hi = a < b ? b : a;
      form.elements.from.value = lo;
      form.elements.to.value = hi;
      form.submit();
    }

    function draw() {
      grid.textContent = "";
      var head = el("div", "pcal__head");
      var prev = el("button", "pcal__nav", "‹");
      prev.type = "button"; prev.setAttribute("aria-label", form.dataset.labelPrev);
      prev.addEventListener("click", function () { step(-1); });
      var next = el("button", "pcal__nav", "›");
      next.type = "button"; next.setAttribute("aria-label", form.dataset.labelNext);
      next.addEventListener("click", function () { step(1); });
      head.append(prev, el("b", "pcal__month", months[view.m] + " " + view.y), next);

      var days = el("div", "pcal__days");
      weekdays.forEach(function (w) { days.appendChild(el("span", "pcal__wd", w)); });
      var lead = (new Date(view.y, view.m, 1).getDay() + 6) % 7; // неделя с понедельника
      for (var i = 0; i < lead; i++) days.appendChild(el("span"));
      var count = new Date(view.y, view.m + 1, 0).getDate();
      var lo = anchor ? (anchor < (hover || anchor) ? anchor : hover || anchor) : from && iso(from.y, from.m, from.d);
      var hi = anchor ? (anchor < (hover || anchor) ? hover || anchor : anchor) : to && iso(to.y, to.m, to.d);
      for (var d = 1; d <= count; d++) {
        var key = iso(view.y, view.m, d);
        var cls = "pcal__day";
        if (key === lo || key === hi) cls += " is-edge";
        else if (lo && hi && key > lo && key < hi) cls += " is-inside";
        if (key === today) cls += " is-today";
        var btn = el("button", cls, String(d));
        btn.type = "button"; btn.dataset.day = key;
        days.appendChild(btn);
      }
      var hint = el("p", "pcal__hint", anchor ? form.dataset.hintEnd : form.dataset.hintStart);
      grid.append(head, days, hint);
    }

    grid.addEventListener("click", function (event) {
      var day = event.target.closest && event.target.closest("[data-day]");
      if (!day) return;
      // Сетка перерисуется, и щелчок окажется «вне» списка: `pick.js` его закрыл бы.
      event.stopPropagation();
      if (!anchor) { anchor = day.dataset.day; hover = anchor; draw(); return; }
      apply(anchor, day.dataset.day);
    });
    grid.addEventListener("mouseover", function (event) {
      var day = event.target.closest && event.target.closest("[data-day]");
      if (!anchor || !day || day.dataset.day === hover) return;
      hover = day.dataset.day;
      draw();
    });
    draw();
  }

  // `toggle` не всплывает — ловим на погружении.
  document.addEventListener("toggle", function (event) {
    var pick = event.target;
    if (!pick.matches || !pick.matches("details.speriod__pick") || !pick.open) return;
    var form = pick.querySelector("form[data-pcal]");
    if (form) build(form);
  }, true);
})();
