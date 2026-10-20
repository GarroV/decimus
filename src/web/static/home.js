/* «Рейтинги» на главной (D583, D584): стрелки и затухание у слайдера колонок.
   Прокрутка пальцем и колесом нативная; скрипт только подсказывает, куда ещё можно. */
(function () {
  "use strict";
  function init(root) {
    var view = root.querySelector("[data-rb-view]");
    if (!view) return;
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
    window.addEventListener("resize", sync);
    sync();
  }
  document.querySelectorAll("[data-rb-scroll]").forEach(init);
})();
