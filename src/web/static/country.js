// «Пиццерии»: список пиццерий выбранной страны живёт в колонке выбора, которая
// прокручивается сама (D510, `decimus-pick.css`). Выбранная строка может
// оказаться за краем — прокручиваем к ней колонку, не страницу.
(function () {
  "use strict";
  var list = document.querySelector("[data-pk-sub]");
  var rail = document.querySelector(".pk-rail");
  if (!list || !rail) return;
  var row = list.querySelector(".is-on");
  if (!row) return;
  var top = row.getBoundingClientRect().top - rail.getBoundingClientRect().top + rail.scrollTop;
  if (top < rail.scrollTop || top + row.offsetHeight > rail.scrollTop + rail.clientHeight) {
    rail.scrollTop = Math.max(0, top - (rail.clientHeight - row.offsetHeight) / 2);
  }
})();
