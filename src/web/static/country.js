// «Страна»: список пиццерий прокручивается внутри колонки (D510), поэтому
// выбранная строка может оказаться за краем — прокручиваем к ней сам список,
// не страницу.
(function () {
  "use strict";
  var list = document.querySelector("[data-cn-ulist]");
  if (!list) return;
  var row = list.querySelector(".is-on");
  if (!row) return;
  var below = row.offsetTop + row.offsetHeight - list.clientHeight;
  if (row.offsetTop < list.scrollTop || below > list.scrollTop) {
    list.scrollTop = Math.max(0, row.offsetTop - (list.clientHeight - row.offsetHeight) / 2);
  }
})();
