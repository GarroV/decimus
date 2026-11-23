// One pending page request across the shell and Ratings navigation.
(function () {
  "use strict";
  if (!window.AbortController) return;
  var active = null;
  var target = null;
  var sequence = 0;
  window.decimusNavigation = {
    isPending: function (href) {
      return active !== null && target === new URL(href, location.href).href;
    },
    start: function (href) {
      var id = ++sequence;
      if (active) active.abort();
      var controller = new AbortController();
      active = controller;
      target = new URL(href, location.href).href;
      var timer = setTimeout(function () { controller.abort(); }, 20000);
      var root = document.documentElement;
      var status = document.querySelector("[data-navigation-status]");
      var main = document.querySelector("main.shell__main");
      root.classList.add("is-navigating");
      if (status) status.hidden = false;
      if (main) main.setAttribute("aria-busy", "true");
      document.querySelectorAll(".sidenav__list a[href]").forEach(function (link) {
        link.classList.toggle("is-pending", new URL(link.href).pathname === new URL(href, location.href).pathname);
      });
      return {
        signal: controller.signal,
        current: function () { return id === sequence; },
        finish: function () {
          clearTimeout(timer);
          if (id !== sequence) return;
          active = null;
          target = null;
          root.classList.remove("is-navigating");
          if (status) status.hidden = true;
          document.querySelectorAll('main[aria-busy], .sidenav__list .is-pending').forEach(function (node) {
            node.removeAttribute("aria-busy");
            node.classList.remove("is-pending");
          });
        }
      };
    }
  };
})();
