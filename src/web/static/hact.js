// Ряд действий карточки проверки (`_card_parts.html`, макрос `card_actions`).
//
// Без скрипта окно действия — всплывающий блок под рядом (`.hact__pop`, absolute): ряд
// не двигается, но окно лежит поверх содержимого. Со скриптом раскрытое окно переезжает
// в слот под всем рядом (`.hact__slot`), в поток: ряд кнопок остаётся на своих местах,
// содержимое ниже сдвигается. Закрытие возвращает окно в свой `<details>`. Одна открытая
// за раз держит `<details name="hact">`, а не этот файл.
(function () {
  "use strict";

  function slotOf(row) {
    var slot = row.querySelector(":scope > .hact__slot");
    if (!slot) {
      slot = document.createElement("div");
      slot.className = "hact__slot";
      row.appendChild(slot);
    }
    return slot;
  }

  function sync(item) {
    var row = item.closest(".hact");
    if (!row) return;
    var home = item.querySelector(":scope > .hact__pop");
    if (item.open && home) {
      var pop = home;
      pop.hact_home = item;
      slotOf(row).appendChild(pop);
    } else if (!item.open) {
      var slot = row.querySelector(":scope > .hact__slot");
      var moved = slot && Array.prototype.find.call(slot.children, function (el) {
        return el.hact_home === item;
      });
      if (moved) item.appendChild(moved);
    }
  }

  // `toggle` не всплывает — слушаем в фазе перехвата, работает и для подменённых панелей.
  document.addEventListener("toggle", function (e) {
    var item = e.target;
    if (item && item.matches && item.matches("details.hact__item")) sync(item);
  }, true);
})();
