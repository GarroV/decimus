/* «Рейтинги» на главной (D583, D584): стрелки и затухание у слайдера колонок.
   Прокрутка пальцем и колесом нативная; скрипт только подсказывает, куда ещё можно. */
(function () {
  "use strict";
  function init(root) {
    var view = root.querySelector("[data-rb-view]");
    if (!view || root.hasAttribute("data-rb-ready")) return;
    root.setAttribute("data-rb-ready", "");
    function sync() {
      var max = view.scrollWidth - view.clientWidth;
      root.classList.toggle("can-prev", view.scrollLeft > 1);
      root.classList.toggle("can-next", view.scrollLeft < max - 1);
    }
    root.querySelectorAll("[data-rb-step]").forEach(function (btn) {
      btn.hidden = false;
      btn.addEventListener("click", function () {
        var dir = Number(btn.getAttribute("data-rb-step"));
        view.scrollBy({ left: dir * view.clientWidth * 0.7, behavior: "smooth" });
      });
    });
    view.addEventListener("scroll", sync, { passive: true });
    window.addEventListener("resize", function () {
      if (view.isConnected) sync();
    });
    sync();
  }
  function start() { document.querySelectorAll("[data-rb-scroll]").forEach(init); }
  // Запускается при загрузке и при каждом приходе на экран переходом `nav.js`.
  document.addEventListener("decimus:navigation", start);
  start();
})();
