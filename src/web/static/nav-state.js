// Ширина панели и раскрытие веток выбираются человеком, а не текущим экраном.
// Выполняется до CSS: при полной навигации не возникает широкой вспышки.
// Ширину меняет только кнопка свёртки. «Рейтинги» в узкой панели (рейле) раскрываются
// всплывающим списком рядом с панелью (`data-nav-fly`), а не растягивают её: переключение
// раздела ничего не двигает на странице (владелец 09.11.2026).
(function () {
  "use strict";
  var root = document.documentElement;
  var widthKey = "decimus-nav-collapsed";
  var ratingsKey = "decimus-nav-ratings-open";
  function read(key) { try { return localStorage.getItem(key); } catch (_) { return null; } }
  function write(key, value) { try { localStorage.setItem(key, value); } catch (_) { /* private browsing */ } }
  var initial = read(widthKey);
  root.dataset.navCollapsed = initial === null ? String(innerWidth < 1100) : initial;
  function ratingsDefault() {
    var branch = read(ratingsKey);
    return branch === null ? String(/\/ratings(?:\/|$)/.test(location.pathname)) : branch;
  }
  root.dataset.navRatingsOpen = ratingsDefault();
  root.dataset.navFly = "false";
  function closeFly() {
    if (root.dataset.navFly === "true") { root.dataset.navFly = "false"; mark(); }
  }
  function mark() {
    var collapsed = root.dataset.navCollapsed === "true";
    document.querySelectorAll("[data-nav-collapse]").forEach(function (button) {
      button.setAttribute("aria-expanded", String(!collapsed));
      var label = collapsed ? button.dataset.expandLabel : button.dataset.collapseLabel;
      button.setAttribute("aria-label", label);
      button.title = label;
      var text = button.querySelector(".sidenav__label");
      if (text) text.textContent = label;
    });
    document.querySelectorAll("[data-nav-ratings-toggle]").forEach(function (button) {
      var shown = collapsed ? root.dataset.navFly === "true" : root.dataset.navRatingsOpen === "true";
      button.setAttribute("aria-expanded", String(shown));
    });
    var panel = document.getElementById("ratings-navigation");
    if (panel) panel.inert = collapsed ? root.dataset.navFly !== "true" : root.dataset.navRatingsOpen !== "true";
  }
  document.addEventListener("click", function (event) {
    var target = event.target.closest && event.target.closest("[data-nav-collapse], [data-nav-ratings-toggle]");
    if (!target) {
      if (!event.target.closest || !event.target.closest(".sidenav__branch-clip")) closeFly();
      return;
    }
    event.preventDefault();
    if (target.hasAttribute("data-nav-collapse")) {
      root.dataset.navFly = "false";
      root.dataset.navCollapsed = String(root.dataset.navCollapsed !== "true");
      write(widthKey, root.dataset.navCollapsed);
    } else if (root.dataset.navCollapsed === "true") {
      var box = target.getBoundingClientRect();
      root.style.setProperty("--fly-top", Math.max(8, Math.round(box.top)) + "px");
      root.dataset.navFly = String(root.dataset.navFly !== "true");
    } else {
      root.dataset.navRatingsOpen = String(root.dataset.navRatingsOpen !== "true");
      write(ratingsKey, root.dataset.navRatingsOpen);
    }
    mark();
  });
  document.addEventListener("keydown", function (event) { if (event.key === "Escape") closeFly(); });
  window.addEventListener("resize", closeFly);
  document.addEventListener("DOMContentLoaded", mark);
  document.addEventListener("decimus:navigation", function () {
    // Без выбора человека ветка раскрыта по адресу — и при подмене страницы тоже,
    // иначе полная загрузка и подмена показывали бы её по-разному.
    root.dataset.navRatingsOpen = ratingsDefault();
    root.dataset.navFly = "false";
    mark();
  });
})();
