// «Страны» (D536): строки колонки выбора — страна и пиццерия — открываются без
// перескока страницы (D527). Нажатие на строку запрашивает тот же экран фоном и
// подменяет колонку и рабочую область; адрес меняется, «назад» браузера работает,
// колонка не теряет прокрутки. Без скрипта строки — обычные ссылки, экран тот же.
//
// Список пиццерий выбранной страны живёт в колонке, которая прокручивается сама
// (D510, `decimus-pick.css`): выбранная строка может оказаться за краем, и
// колонка прокручивается к ней (не страница).
(function () {
  "use strict";

  function railOf() {
    return document.querySelector(".pk-rail");
  }

  function scrollToSelected() {
    var rail = railOf();
    var list = document.querySelector("[data-pk-sub]");
    if (!list || !rail) return;
    var row = list.querySelector(".is-on");
    if (!row) return;
    var top = row.getBoundingClientRect().top - rail.getBoundingClientRect().top + rail.scrollTop;
    if (top < rail.scrollTop || top + row.offsetHeight > rail.scrollTop + rail.clientHeight) {
      rail.scrollTop = Math.max(0, top - (rail.clientHeight - row.offsetHeight) / 2);
    }
  }

  function plainClick(e) {
    return e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;
  }

  function swap(href, push) {
    fetch(href, { credentials: "same-origin", headers: { Accept: "text/html" } })
      .then(function (r) {
        if (!r.ok || r.redirected) throw new Error("status");
        return r.text();
      })
      .then(function (html) {
        var doc = new DOMParser().parseFromString(html, "text/html");
        var next = doc.querySelector(".pk-shell");
        var shell = document.querySelector(".pk-shell");
        if (!next || !shell) throw new Error("no shell");
        var rail = railOf();
        var keep = rail ? rail.scrollTop : 0;
        shell.innerHTML = next.innerHTML;
        var drawer = document.querySelector("[data-drawer]");
        var fresh = doc.querySelector("[data-drawer]");
        if (drawer) drawer.remove();
        if (fresh) shell.after(document.importNode(fresh, true));
        document.title = doc.title;
        if (push) history.pushState({ pick: true }, "", href);
        if (railOf()) railOf().scrollTop = keep;
        scrollToSelected();
      })
      .catch(function () {
        window.location.href = href;
      });
  }

  if (window.fetch && window.DOMParser) {
    document.addEventListener("click", function (e) {
      if (!plainClick(e)) return;
      var link = e.target.closest(".pk-rail a.pk-item");
      if (!link || link.hasAttribute("data-drawer-open")) return;
      e.preventDefault();
      swap(link.href, true);
    });
    window.addEventListener("popstate", function (e) {
      if (e.state && e.state.pick) swap(window.location.href, false);
    });
  }

  if (window.history && history.replaceState) history.replaceState({ pick: true }, "", window.location.href);
  scrollToSelected();
})();
