/* Keep the current compact filters, with an accessible fold on small screens. */
(function () {
  "use strict";
  var narrow = window.matchMedia("(max-width: 719px)");
  function bind(force) {
    document.querySelectorAll("[data-registry-fold]").forEach(function (fold) {
      if (!force && fold.dataset.registryFoldReady) return;
      fold.open = !narrow.matches;
      fold.dataset.registryFoldReady = "1";
    });
  }
  narrow.addEventListener("change", function () { bind(true); });
  document.addEventListener("decimus:page", function () { bind(false); });
  document.addEventListener("DOMContentLoaded", function () { bind(false); });
  bind(false);
}());
