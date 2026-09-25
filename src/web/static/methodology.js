// Экран чек-листа (D197): клавиши поверх ссылок. Каждое действие — это уже
// ссылка на странице (соседний пункт, закрыть панель), скрипт только нажимает
// её с клавиатуры. Не загрузился — всё работает мышью, как без него.
(function () {
  "use strict";
  function typing(target) {
    var tag = target && target.tagName;
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (target && target.isContentEditable);
  }
  function go(selector) {
    var link = document.querySelector(selector);
    if (!link) return false;
    window.location.assign(link.href);
    return true;
  }
  document.addEventListener("keydown", function (event) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    if (typing(event.target)) {
      if (event.key === "Escape") event.target.blur();
      return;
    }
    // Открытый чип или форма правки закрываются первыми: Esc снимает верхний слой.
    if (event.key === "Escape" && document.querySelector("details.pick[open], details.mx-edit[open]")) {
      document.querySelectorAll("details.mx-edit[open]").forEach(function (d) { d.removeAttribute("open"); });
      return;
    }
    var handled = false;
    if (event.key === "Escape") handled = go("[data-mx-close]");
    else if (event.key === "ArrowDown" || event.key === "j") handled = go("[data-mx-next]");
    else if (event.key === "ArrowUp" || event.key === "k") handled = go("[data-mx-prev]");
    else if (event.key === "/") {
      var search = document.querySelector("[data-mx-search]");
      if (search) { search.focus(); search.select(); handled = true; }
    }
    if (handled) event.preventDefault();
  });
  // Выбранный пункт — на виду: после перехода стрелкой список не должен
  // оставлять его за краем экрана.
  var current = document.querySelector(".mx-row.is-on");
  if (current && current.scrollIntoView) current.scrollIntoView({ block: "nearest" });
})();
