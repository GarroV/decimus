// Отбор раздела «Рейтинги» применяется сразу (D337): сменил девелопера или
// страну — страница перестраивается без кнопки. Срез и период — ссылки, им
// скрипт не нужен. Не загрузился — под <noscript> остаётся кнопка «Показать».
(function () {
  "use strict";
  document.addEventListener("change", function (event) {
    var form = event.target.closest && event.target.closest("form[data-rt-auto]");
    if (form && event.target.tagName === "SELECT") form.submit();
  });
})();
