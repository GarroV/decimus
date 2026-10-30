/* Мини-апп обхода: блок «Ещё не смотрели» внутри зоны (#837, D492).
 *
 * Пункты методики этой зоны, по которым записи ещё нет, — короткими строками.
 * Нажатие открывает форму записи уже с этим пунктом. Развёрнут, пока в зоне
 * нет записей; после первой записи свёрнут. Руками раскрытое помним до конца
 * сеанса. Замеры (сведения без баллов) — отдельной приглушённой строкой.
 * Ничего не блокирует завершение: это подсказка, бот о ней не знает.
 */
(function () {
  "use strict";

  var W = window.DecimusWalk;
  var tx = W.tx;
  var el = W.el;

  /** Выбор человека по зонам: {код зоны: развёрнут ли}. Нет выбора — по умолчанию. */
  var chosen = {};

  function isOpen(zone) {
    return Object.prototype.hasOwnProperty.call(chosen, zone.code) ? chosen[zone.code] : zone.recorded.length === 0;
  }

  /** Блок для зоны или null, если показывать нечего (или запись закрыта). */
  W.unseenBlock = function (zone, writable) {
    var unseen = zone.unseen || [];
    var info = zone.unseen_info || [];
    if (!writable || (!unseen.length && !info.length)) return null;
    var open = isOpen(zone);
    var box = el("section", "walk-cl walk-cl--unseen" + (open ? " is-open" : ""));

    if (unseen.length) {
      var wrap = el("div", "walk-cl__wrap");
      wrap.inert = !open;
      var head = W.button("walk-cl__head", null, function () {
        open = !open;
        chosen[zone.code] = open;
        box.classList.toggle("is-open", open);
        head.setAttribute("aria-expanded", open ? "true" : "false");
        wrap.inert = !open;
      });
      head.setAttribute("aria-expanded", open ? "true" : "false");
      head.appendChild(el("span", "walk-cl__title", tx("walk.unseen.title")));
      head.appendChild(el("span", "walk-cl__count", String(unseen.length)));
      head.appendChild(el("span", "walk-cl__caret", "▾"));
      box.appendChild(head);

      var inner = el("div", "walk-cl__inner");
      var list = el("ul", "walk-cl__list");
      unseen.forEach(function (i) {
        var li = el("li");
        var b = W.button("walk-cl__item", null, function () {
          W.sheet.open({ mode: "violation", zone: zone.code, code: i.code, level: i.levels.length === 1 ? i.levels[0] : null });
        });
        b.appendChild(el("span", "walk-cl__text", i.q));
        b.appendChild(el("span", "walk-cl__act", "+"));
        li.appendChild(b);
        list.appendChild(li);
      });
      inner.appendChild(list);
      wrap.appendChild(inner);
      box.appendChild(wrap);
    }

    if (info.length) {
      var line = el("p", "walk-unseen__info");
      line.appendChild(el("span", "walk-unseen__label", tx("walk.unseen.info")));
      info.forEach(function (i) {
        line.appendChild(W.button("walk-unseen__link", i.q, function () {
          W.sheet.open({ mode: "measure", zone: zone.code, code: i.code, level: "D0" });
        }));
      });
      box.appendChild(line);
    }
    return box;
  };
})();
