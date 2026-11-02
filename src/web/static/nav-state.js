// Ширина панели и раскрытие веток выбираются человеком, а не текущим экраном.
// Выполняется до CSS: при полной навигации не возникает широкой вспышки.
(function () {
  "use strict";
  var root = document.documentElement;
  var widthKey = "decimus-nav-collapsed";
  var ratingsKey = "decimus-nav-ratings-open";
  function read(key) { try { return localStorage.getItem(key); } catch (_) { return null; } }
  function write(key, value) { try { localStorage.setItem(key, value); } catch (_) { /* private browsing */ } }
  var initial = read(widthKey);
  root.dataset.navCollapsed = initial === null ? String(innerWidth < 1100) : initial;
  var branch = read(ratingsKey);
  root.dataset.navRatingsOpen = branch === null ? String(/\/ratings(?:\/|$)/.test(location.pathname)) : branch;
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
      button.setAttribute("aria-expanded", root.dataset.navRatingsOpen);
    });
    var panel = document.getElementById("ratings-navigation");
    if (panel) panel.inert = collapsed || root.dataset.navRatingsOpen !== "true";
  }
  document.addEventListener("click", function (event) {
    var target = event.target.closest && event.target.closest("[data-nav-collapse], [data-nav-ratings-toggle]");
    if (!target) return;
    event.preventDefault();
    if (target.hasAttribute("data-nav-collapse")) {
      root.dataset.navCollapsed = String(root.dataset.navCollapsed !== "true");
      write(widthKey, root.dataset.navCollapsed);
    } else {
      if (root.dataset.navCollapsed === "true") {
        root.dataset.navCollapsed = "false";
        write(widthKey, "false");
        root.dataset.navRatingsOpen = "true";
      } else root.dataset.navRatingsOpen = String(root.dataset.navRatingsOpen !== "true");
      write(ratingsKey, root.dataset.navRatingsOpen);
    }
    mark();
  });
  document.addEventListener("DOMContentLoaded", mark);
  document.addEventListener("decimus:navigation", mark);
})();
