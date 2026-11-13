// Мягкое подключение защиты: «Позже» скрывает предложение до следующего входа.
(function () {
  "use strict";
  function init() {
    var reminder = document.querySelector("[data-security-reminder]");
    if (!reminder) return;
    var key = "decimus-security-later";
    try { reminder.hidden = localStorage.getItem(key) === reminder.dataset.session; } catch (_) {}
    var later = reminder.querySelector("[data-security-later]");
    later.hidden = false;
    later.onclick = function () {
      reminder.hidden = true;
      try { localStorage.setItem(key, reminder.dataset.session); } catch (_) {}
    };
  }
  init();
  document.addEventListener("decimus:page", init);
}());
