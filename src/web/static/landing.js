/* Посадочная страница (D546): листы наезжают друг на друга через `position: sticky`.
   Лист выше окна (телефон) прижимался бы верхом и обрезал свой низ, поэтому ему
   даётся меньший `top` (вплоть до отрицательного): он докручивается до конца и только потом прилипает.
   Второе — полоса закладок: лист, дошедший до верха, оставляет закладку в полосе под
   шапкой, и закладки складываются слева направо; на прокрутке вверх уходят обратно на листы. */
(function () {
  "use strict";
  var sheets = document.querySelectorAll(".lp-sheet");
  if (!sheets.length) return;

  var head = document.querySelector(".lp-bar");
  // Закладка листа → её копия в полосе. Цвет копии — цвет листа, он задан на листе.
  var tabs = Array.prototype.map.call(document.querySelectorAll(".lp-sheet > .lp-tab"), function (tab) {
    return { tab: tab, sheet: tab.parentNode, copy: tab.cloneNode(true) };
  });
  var strip = document.createElement("div");
  strip.className = "lp-tabs";
  strip.setAttribute("aria-hidden", "true");
  tabs.forEach(function (t) { strip.appendChild(t.copy); });
  if (tabs.length) document.querySelector(".lp").appendChild(strip);

  function barH() { return head ? head.offsetHeight : 0; }
  function stripH() { return tabs.length ? tabs[0].tab.offsetHeight : 0; }

  function place() {
    // Шапка прилипает сверху над листами; первый лист — под ней, листы с закладкой —
    // ещё ниже на полосу закладок, чтобы полоса не закрывала их верх.
    var bar = barH();
    for (var i = 0; i < sheets.length; i++) {
      var s = sheets[i];
      var top = s.classList.contains("lp-hero") ? bar : bar + stripH();
      s.style.top = Math.min(top, window.innerHeight - s.offsetHeight) + "px";
    }
    tabs.forEach(function (t) {
      var box = t.sheet.getBoundingClientRect();
      t.copy.style.left = box.left + t.tab.offsetLeft + "px";
      t.copy.style.background = getComputedStyle(t.sheet).backgroundColor;
    });
    dock();
  }

  // Закладка в полосе, пока верх её листа выше нижнего края полосы.
  function dock() {
    var line = barH() + stripH() + 0.5;
    tabs.forEach(function (t) {
      var on = t.sheet.getBoundingClientRect().top <= line;
      t.copy.classList.toggle("is-on", on);
      t.tab.classList.toggle("is-docked", on);
    });
  }

  var pending = false;
  window.addEventListener("scroll", function () {
    if (pending) return;
    pending = true;
    window.requestAnimationFrame(function () { pending = false; dock(); });
  }, { passive: true });

  place();
  window.addEventListener("resize", place);
  // Картинки подгружаются лениво и меняют высоту листа — пересчитываем по мере загрузки.
  window.addEventListener("load", place);
  var imgs = document.querySelectorAll(".lp-sheet img");
  for (var j = 0; j < imgs.length; j++) imgs[j].addEventListener("load", place);
})();
