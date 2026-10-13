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
    if (panel) panel.querySelector(".sdetail__head").after(note);
  }

  // Действие в панели — фоном: форму принимает сервер, обратно приходит та же
  // карточка с итогом («принята» или причина отказа), и панель остаётся открытой
  // на том же месте. Не вышло дойти до сервера — сказано в панели, форма цела.
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form.matches || !form.matches("[data-drawer] form[data-panel-form]")) return;
    if (!window.fetch || !window.FormData) return;
    e.preventDefault();
    if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) return;
    var body = form.closest(".sdrawer__body");
    var top = body.scrollTop;
    var wasEditing = !!body.querySelector(".spanel.is-editing");
    var buttons = form.querySelectorAll("button[type=submit]");
    buttons.forEach(function (b) {
      b.disabled = true;
    });
    fetch(form.action, {
      method: "POST",
      body: new FormData(form),
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
        if (wasEditing) setEditing(node, true);
        bind(node);
        body.scrollTop = top;
        var note = node.querySelector(".note--ok, .note--error");
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

  // «Исправить» на проверке, ждущей приёмки: режим правки панели (D465) —
  // показать входы в правку записей, показать «✕/Заменить/+ Фото» и «Добавить
  // запись» (повторный щелчок — свернуть). Режим переживает ответ на действие.
  function setEditing(panel, on) {
    panel.classList.toggle("is-editing", on);
    var toggle = panel.querySelector("[data-edit-toggle]");
    if (toggle) toggle.setAttribute("aria-pressed", on ? "true" : "false");
    var sheet = panel.querySelector("#review");
    if (!sheet) return;
    // Формы записей не раскрываем разом (стена полей, D465): режим правки
    // показывает только входы «Править запись»; при выходе всё сворачивается.
    if (!on) {
      sheet.querySelectorAll("details.review-revise, details.review-add").forEach(function (d) {
        d.open = false;
      });
    }
    if (on) {
      sheet.querySelectorAll("details.review-zone").forEach(function (d) {
        d.open = true;
      });
    }
  }

  document.addEventListener("click", function (e) {
    var toggle = e.target.closest("[data-edit-toggle]");
    if (!toggle) return;
    var panel = toggle.closest(".spanel");
    var sheet = panel && panel.querySelector("#review");
    if (!sheet) return;
    e.preventDefault();
    var on = toggle.getAttribute("aria-pressed") !== "true";
    setEditing(panel, on);
    if (on) sheet.scrollIntoView({ block: "start", behavior: "smooth" });
  });

  // Файл выбран — форма уходит сразу: «Заменить» и «+ Фото» без отдельной кнопки.
  document.addEventListener("change", function (e) {
    var input = e.target;
    if (!input.matches || !input.matches("input[type=file][data-autofile]")) return;
    if (!input.files || !input.files.length) return;
    if (input.form && input.form.requestSubmit) input.form.requestSubmit();
  });

  // Поиск пункта в форме «Добавить запись»: список сужается по коду и названию.
  document.addEventListener("input", function (e) {
    var box = e.target;
    if (!box.matches || !box.matches("input[data-pick-filter]")) return;
    var select = document.querySelector(box.dataset.pickFilter);
    if (!select) return;
    var needle = box.value.trim().toLowerCase();
    var firstShown = null;
    Array.prototype.forEach.call(select.options, function (o) {
      var hit = !needle || o.textContent.toLowerCase().indexOf(needle) !== -1;
      o.hidden = !hit;
      o.disabled = !hit;
      if (hit && !firstShown) firstShown = o;
    });
    if (select.selectedOptions.length && select.selectedOptions[0].disabled) {
      select.selectedIndex = firstShown ? firstShown.index : -1;
    }
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
