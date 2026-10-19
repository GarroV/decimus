// Фото записи открывается и сворачивается по клику в том же окне (D534).
// Ссылка `a[data-zoom]` без скрипта ведёт на сам снимок; со скриптом клик
// раскрывает его поверх страницы. Закрытие — клик по снимку или по полю, Esc;
// фокус возвращается на ссылку. Адрес снимка берётся из ссылки как есть.
(function () {
  "use strict";

  var box = null;
  var opener = null;

  function close() {
    if (!box) return;
    box.remove();
    box = null;
    document.removeEventListener("keydown", onKey, true);
    if (opener) opener.focus({ preventScroll: true });
    opener = null;
  }

  function onKey(e) {
    if (e.key !== "Escape") return;
    e.preventDefault();
    e.stopPropagation(); // Esc не должен заодно закрыть панель проверки (`split.js`)
    close();
  }

  function open(link) {
    close();
    opener = link;
    var thumb = link.querySelector("img");
    var img = document.createElement("img");
    img.className = "zoom__img";
    img.src = link.href;
    img.alt = thumb ? thumb.alt : "";
    box = document.createElement("button");
    box.type = "button";
    box.className = "zoom";
    box.setAttribute("aria-label", img.alt);
    box.appendChild(img);
    box.addEventListener("click", close);
    document.body.appendChild(box);
    box.focus({ preventScroll: true });
    document.addEventListener("keydown", onKey, true);
  }

  document.addEventListener("click", function (e) {
    var link = e.target.closest && e.target.closest("a[data-zoom]");
    if (!link || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    open(link);
  });
})();
