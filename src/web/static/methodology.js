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
  // «Набрано» под долями зон — подсказка при вводе, а не проверка: сумму
  // судит движок, и версию с несошедшейся он не примет.
  var sharesForm = document.querySelector("[data-mx-shares]");
  var sumCell = document.querySelector("[data-mx-share-sum]");
  function recount() {
    var total = 0;
    var ok = true;
    sharesForm.querySelectorAll("[data-mx-share]").forEach(function (input) {
      var raw = input.value.trim().replace(",", ".");
      if (raw === "") return;
      var n = Number(raw);
      if (isNaN(n)) ok = false; else total += n;
    });
    sumCell.textContent = ok ? (Math.round(total * 100) / 100) + "%" : "—";
  }
  if (sharesForm && sumCell) {
    sharesForm.addEventListener("input", recount);
    recount();
  }
  // Выбранный пункт — на виду: после перехода стрелкой список не должен
  // оставлять его за краем экрана.
  var current = document.querySelector(".mx-row.is-on");
  if (current && current.scrollIntoView) current.scrollIntoView({ block: "nearest" });
})();
