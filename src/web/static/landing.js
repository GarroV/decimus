/* Посадочная страница (D546): листы наезжают друг на друга через `position: sticky`.
   Лист выше окна (телефон) прижимался бы верхом и обрезал свой низ, поэтому ему
   даётся меньший `top` (вплоть до отрицательного): он докручивается до конца и только потом прилипает.
   Больше скрипт ничего не делает — ни анимаций, ни привязки к прокрутке. */
(function () {
  "use strict";
  var sheets = document.querySelectorAll(".lp-sheet");
  if (!sheets.length) return;

  function place() {
    // Шапка прилипает сверху над листами; листы прилипают под ней.
    var head = document.querySelector(".lp-bar");
    var bar = head ? head.offsetHeight : 0;
    for (var i = 0; i < sheets.length; i++) {
      var s = sheets[i];
      s.style.top = Math.min(bar, window.innerHeight - s.offsetHeight) + "px";
    }
  }

  place();
  window.addEventListener("resize", place);
  // Картинки подгружаются лениво и меняют высоту листа — пересчитываем по мере загрузки.
  window.addEventListener("load", place);
  var imgs = document.querySelectorAll(".lp-sheet img");
  for (var j = 0; j < imgs.length; j++) imgs[j].addEventListener("load", place);
})();
