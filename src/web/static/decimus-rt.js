// Отбор раздела «Рейтинги» применяется сразу (D357): сменил девелопера или
// страну — страница перестраивается без кнопки. Срез и период — ссылки, им
// скрипт не нужен. Не загрузился — под <noscript> остаётся кнопка «Показать».
(function () {
  "use strict";
  document.addEventListener("change", function (event) {
    var form = event.target.closest && event.target.closest("form[data-rt-auto]");
    if (form && event.target.tagName === "SELECT") form.submit();
  });

  // Подсказка свечи — сразу при наведении или фокусе (D385): системная по
  // `title` всплывает через секунду. <title> остаётся для экранных чтецов.
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
})();
