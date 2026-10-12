/* Мини-апп обхода: всплывающее меню поверх формы записи (D330).
 *
 * Выбор, который делают редко (зона, вид записи, пункт вручную), не лежит на
 * форме облаком кнопок, а открывается снизу по нажатию и закрывается после
 * выбора. Форма остаётся про главное: кадр, слова, что нашла система.
 *
 *   W.menu.open({ title, options: [{ label, hint, code, on, value }], onPick })
 *   W.menu.search({ title, placeholder, lead, list(query), onPick })
 *
 * `list(query)` отдаёт варианты так же, как `options`; `lead` — варианты,
 * которые стоят первыми без запроса (общая заметка у рекомендации).
 */
(function () {
  "use strict";

  var W = window.DecimusWalk;
  var tx = W.tx;
  var el = W.el;
  var LIMIT = 60;
  var node = null;

  function close() {
    if (!node) return;
    node.remove();
    node = null;
    document.removeEventListener("keydown", onKey);
  }

  function onKey(e) { if (e.key === "Escape") close(); }

  function frame(title) {
    close();
    node = el("div", "walk-menu");
    node.setAttribute("role", "dialog");
    node.setAttribute("aria-modal", "true");
    var shade = W.button("walk-menu__shade", null, close);
    shade.setAttribute("aria-label", tx("walk.sheet.close"));
    node.appendChild(shade);
    var panel = el("div", "walk-menu__panel");
    var head = el("div", "walk-menu__head");
    head.appendChild(el("h3", "walk-menu__title", title));
    var x = W.button("walk-menu__close", "✕", close);
    x.setAttribute("aria-label", tx("walk.sheet.close"));
    head.appendChild(x);
    panel.appendChild(head);
    node.appendChild(panel);
    document.body.appendChild(node);
    document.addEventListener("keydown", onKey);
    return panel;
  }

  function fill(list, options, onPick) {
    list.textContent = "";
    if (!options.length) list.appendChild(el("li", "walk-options__empty", tx("walk.sheet.search_empty")));
    options.slice(0, LIMIT).forEach(function (o) {
      var li = el("li");
      var b = W.button("walk-option" + (o.on ? " is-on" : "") + (o.lead ? " walk-option--note" : ""), null, function () {
        W.haptic();
        close();
        onPick(o.value);
      });
      if (o.code || o.badge) {
        var top = el("span", "walk-option__top");
        if (o.code) top.appendChild(el("span", "walk-option__code", o.code));
        if (o.badge) top.appendChild(el("span", "walk-option__was", o.badge));
        b.appendChild(top);
      }
      b.appendChild(el("span", "walk-option__text", o.label));
      if (o.hint) b.appendChild(el("span", "walk-option__hint", o.hint));
      if (o.on) b.setAttribute("aria-current", "true");
      li.appendChild(b);
      list.appendChild(li);
    });
  }

  function open(opts) {
    var panel = frame(opts.title);
    var list = el("ul", "walk-options walk-menu__list");
    panel.appendChild(list);
    fill(list, opts.options, opts.onPick);
    var on = list.querySelector(".is-on");
    if (on) on.focus(); else if (list.querySelector("button")) list.querySelector("button").focus();
  }

  function search(opts) {
    var panel = frame(opts.title);
    var input = el("input", "walk-search");
    input.type = "search";
    input.placeholder = opts.placeholder;
    input.setAttribute("enterkeyhint", "search");
    var list = el("ul", "walk-options walk-menu__list");
    function refresh() {
      var q = input.value.trim();
      fill(list, (q ? [] : opts.lead || []).concat(opts.list(q)), opts.onPick);
    }
    input.addEventListener("input", refresh);
    panel.appendChild(input);
    panel.appendChild(list);
    refresh();
    input.focus();
  }

  W.menu = { open: open, search: search, close: close, isOpen: function () { return !!node; } };
})();
