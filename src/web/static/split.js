// Каркас «список на всю ширину, выбранное — в панели справа» (`_split_page.html`).
// Страница работает и без этого файла: строка — ссылка, которая рисует
// страницу с открытой панелью; ✕ и затемнение — ссылки закрытия; фильтры —
// кнопкой «Показать»; подтверждение — раскрывающимся блоком. Скрипт добавляет:
//   * открытие панели без перезагрузки (та же страница запрашивается фоном,
//     из ответа берётся панель; адрес меняется, «назад» браузера работает);
//   * закрытие с анимацией выезда, по Esc и по щелчку на затемнении;
//   * фильтры применяются сразу при выборе, кнопка «Показать» прячется;
//   * действия в панели проверки (`form[data-panel-form]`) уходят фоном, ответ
//     подменяет карточку, панель остаётся открытой (D465);
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
    document.querySelectorAll(".split__list .srow, .split__list .pk-item, .pk-work .srow").forEach(function (row) {
      var on = href !== null && row.href === href;
      // Строка списка: `srow` — `is-current`, элемент колонки выбора `pk-item` — `is-on` (D655).
      row.classList.toggle(row.classList.contains("pk-item") ? "is-on" : "is-current", on);
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

  // Вход истёк: сервер уже увёл запрос на форму входа с `next=` на этот адрес
  // (`auth._guard`) — идём туда целиком, и после входа вернёмся на ту же панель.
  function loginWithNext(loginUrl) {
    var u = new URL(loginUrl);
    if (u.searchParams.has("next")) return loginUrl;
    // Ответ на действие (POST) уводит на вход без адреса возврата: добавляем тот
    // же, что у `auth._guard` — путь внутри приложения, без префикса площадки.
    var root = u.pathname.replace(/\/+$/, "").slice(0, -"/login".length);
    var here = window.location.pathname;
    if (root && here.indexOf(root) === 0) here = here.slice(root.length);
    u.searchParams.set("next", here + window.location.search);
    return u.toString();
  }

  function wentToLogin(r) {
    return r.redirected && new URL(r.url).pathname.replace(/\/+$/, "").endsWith("/login");
  }

  // Панель из ответа сервера: страница целиком, из неё берётся только панель.
  // Не вышло (сеть, панели нет) — обычный переход по ссылке; истёкший вход —
  // на форму входа с возвратом сюда.
  function openDrawer(href, push) {
    fetch(href, { credentials: "same-origin", headers: { Accept: "text/html" } })
      .then(function (r) {
        if (wentToLogin(r)) {
          window.location.href = loginWithNext(r.url);
          return null;
        }
        if (!r.ok || r.redirected) throw new Error("status");
        return r.text();
      })
      .then(function (html) {
        if (html === null) return;
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
        else (document.querySelector(".split") || document.querySelector(".pk-shell")).after(node);
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
    var open = e.target.closest(".split__list a.srow, .split__list a.pk-item, a[data-drawer-open]");
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

  function refreshList() {
    fetch(window.location.href, { credentials: "same-origin", headers: { Accept: "text/html" } })
      .then(function (r) {
        return r.ok && !r.redirected ? r.text() : null;
      })
      .then(function (html) {
        if (!html) return;
        var fresh = new DOMParser().parseFromString(html, "text/html").querySelector(".split__list");
        var list = document.querySelector(".split__list");
        if (!fresh || !list) return;
        list.innerHTML = fresh.innerHTML;
        markCurrent(window.location.href);
      })
      .catch(function () {});
  }

  function panelFailed(body) {
    var panel = body.querySelector(".spanel");
    var note = document.createElement("div");
    note.className = "note note--error";
    note.setAttribute("role", "alert");
    note.innerHTML = '<div class="note__text"></div>';
    note.firstChild.textContent = panel ? panel.dataset.netError || "" : "";
    var old = body.querySelector(".note[data-net-note]");
    if (old) old.remove();
    note.setAttribute("data-net-note", "");
    var head = panel && (panel.querySelector(".sdetail__head") || panel.querySelector(".lt__head"));
    if (head) head.after(note);
  }

  // Действие в панели — фоном: форму принимает сервер, обратно приходит та же
  // карточка с итогом («принята» или причина отказа), и панель остаётся открытой
  // на том же месте. Не вышло дойти до сервера — сказано в панели, форма цела.
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form.matches || !form.matches("[data-drawer] form[data-panel-form]")) return;
    if (!window.fetch || !window.FormData) return;
    // Кнопка, которая уводит со страницы (черновик в почте — через окно согласия
    // Google), уходит обычной отправкой: фоном за чужим сайтом не сходить.
    var submitter = e.submitter || null;
    if (submitter && submitter.hasAttribute("data-full-submit")) return;
    e.preventDefault();
    if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) return;
    var body = form.closest(".sdrawer__body");
    var top = body.scrollTop;
    // Правка записи на вычитке (D535): что человек вписал — запоминается, чтобы при
    // отказе сервера форма раскрылась снова с его словами, а не пустой.
    var kept = window.Proofread ? window.Proofread.snapshot(form) : null;
    var buttons = form.querySelectorAll("button[type=submit]");
    buttons.forEach(function (b) {
      b.disabled = true;
    });
    // У формы может быть несколько кнопок со своим адресом (`formaction`):
    // уходит туда, куда вела нажатая, и с её именем и значением.
    var action = (submitter && submitter.getAttribute("formaction")) || form.action;
    var payload = new FormData(form);
    if (submitter && submitter.name) payload.append(submitter.name, submitter.value);
    fetch(action, {
      method: "POST",
      body: payload,
      credentials: "same-origin",
      headers: { "X-Panel": "1" },
    })
      .then(function (r) {
        if (wentToLogin(r)) {
          window.location.href = loginWithNext(r.url);
          return null;
        }
        return r.text().then(function (html) {
          return { ok: r.ok, html: html };
        });
      })
      .then(function (res) {
        if (res === null) return;
        var tpl = document.createElement("template");
        tpl.innerHTML = res.html;
        var next = tpl.content.querySelector(".spanel");
        if (!res.ok || !next) throw new Error("status");
        var node = document.importNode(next, true);
        body.querySelector(".spanel").replaceWith(node);
        bind(node);
        body.scrollTop = top;
        var note = node.querySelector(".note--ok, .note--error");
        if (kept && note && note.classList.contains("note--error")) window.Proofread.restore(node, kept);
        if (note) note.scrollIntoView({ block: "nearest" });
        refreshList();
      })
      .catch(function () {
        buttons.forEach(function (b) {
          b.disabled = false;
        });
        panelFailed(body);
      });
  });

  function bind(root) {
    if (window.LetterEditor) window.LetterEditor.init(root);
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
