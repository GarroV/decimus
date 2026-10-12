// Каркас «список на всю ширину, выбранное — в панели справа» (`_split_page.html`).
// Страница работает и без этого файла: строка — ссылка, которая рисует
// страницу с открытой панелью; ✕ и затемнение — ссылки закрытия; фильтры —
// кнопкой «Показать»; подтверждение — раскрывающимся блоком. Скрипт добавляет:
//   * открытие панели без перезагрузки (та же страница запрашивается фоном,
//     из ответа берётся панель; адрес меняется, «назад» браузера работает);
//   * закрытие с анимацией выезда, по Esc и по щелчку на затемнении;
//   * фильтры применяются сразу при выборе, кнопка «Показать» прячется;
//   * «Скопировать» у одноразового пароля;
//   * в форме «Новый человек» роли сужаются под выбранное пространство.
(function () {
  "use strict";

  var CLOSE_MS = 100; // длительность выезда — как у панели задачи Swarm (TaskModal)

  function typing(el) {
    return el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT");
  }

  function drawer() {
    return document.querySelector("[data-drawer]");
  }

  function markCurrent(href) {
    document.querySelectorAll(".split__list .srow").forEach(function (row) {
      var on = href !== null && row.href === href;
      row.classList.toggle("is-current", on);
      if (on) row.setAttribute("aria-current", "true");
      else row.removeAttribute("aria-current");
    });
  }

  function focusClose() {
    var close = document.querySelector(".sdrawer__close");
    if (close) close.focus({ preventScroll: true });
  }

  function closeDrawer(href, push) {
    var d = drawer();
    if (!d) return;
    d.classList.add("is-closing");
    window.setTimeout(function () {
      d.remove();
      markCurrent(null);
    }, CLOSE_MS);
    if (push) history.pushState({ split: true }, "", href);
  }

  // Панель из ответа сервера: страница целиком, из неё берётся только панель.
  // Не вышло (сеть, вход истёк, панели нет) — обычный переход по ссылке.
  function openDrawer(href, push) {
    fetch(href, { credentials: "same-origin", headers: { Accept: "text/html" } })
      .then(function (r) {
        if (!r.ok || r.redirected) throw new Error("status");
        return r.text();
      })
      .then(function (html) {
        var doc = new DOMParser().parseFromString(html, "text/html");
        var next = doc.querySelector("[data-drawer]");
        if (!next && !push) {
          closeDrawer(href, false); // «назад» к адресу без выбора
          return;
        }
        if (!next) throw new Error("no drawer");
        var node = document.importNode(next, true);
        var old = drawer();
        if (old) old.replaceWith(node);
        else document.querySelector(".split").after(node);
        if (push) history.pushState({ split: true }, "", href);
        markCurrent(href);
        bind(node);
        focusClose();
      })
      .catch(function () {
        window.location.href = href;
      });
  }

  function plainClick(e) {
    return e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;
  }

  document.addEventListener("click", function (e) {
    if (!plainClick(e)) return;
    var close = e.target.closest("[data-drawer-close]");
    if (close) {
      e.preventDefault();
      closeDrawer(close.href, true);
      return;
    }
    var open = e.target.closest(".split__list a.srow, a[data-drawer-open]");
    if (open && window.fetch && window.DOMParser) {
      e.preventDefault();
      openDrawer(open.href, true);
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape" || typing(document.activeElement)) return;
    var close = document.querySelector("[data-drawer] [data-drawer-close]");
    if (close) closeDrawer(close.href, true);
  });

  // «Назад» браузера: адрес уже сменился — панель приводится к нему.
  window.addEventListener("popstate", function () {
    openDrawer(window.location.href, false);
  });

  function bind(root) {
    root.querySelectorAll("form[data-autosubmit]").forEach(function (form) {
      var button = form.querySelector("[data-autosubmit-button]");
      if (button) button.hidden = true;
      form.addEventListener("change", function (e) {
        if (e.target && e.target.type !== "search") form.submit();
      });
    });

    root.querySelectorAll("[data-copy]").forEach(function (button) {
      var source = document.querySelector(button.dataset.copy);
      if (!source || !navigator.clipboard) return;
      button.hidden = false;
      button.addEventListener("click", function () {
        navigator.clipboard.writeText(source.textContent.trim()).then(function () {
          button.textContent = button.dataset.copied;
        });
      });
    });

    root.querySelectorAll("form[data-role-by-space]").forEach(function (form) {
      var select = form.querySelector("[data-space-select]");
      if (!select) return;
      function narrow() {
        var first = null;
        form.querySelectorAll(".srole[data-spaces]").forEach(function (label) {
          var fits = (" " + label.dataset.spaces).indexOf(" " + select.value + " ") !== -1;
          label.hidden = !fits;
          var radio = label.querySelector("input");
          radio.disabled = !fits;
          if (fits && !first) first = radio;
          if (!fits) radio.checked = false;
        });
        if (first && !form.querySelector(".srole input:checked")) first.checked = true;
      }
      select.addEventListener("change", narrow);
      narrow();
    });
  }

  bind(document);
})();
