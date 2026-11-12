// Блок «История проверок» (D751): группировка и год применяются сразу при выборе, без кнопки
// «Показать». Без скрипта работает обычная отправка формы (кнопка под <noscript>).
(function () {
  if (window.__historyAuto) return;
  window.__historyAuto = true;
  document.addEventListener("change", function (event) {
    var select = event.target;
    var form = select && select.closest && select.closest("form[data-history-auto]");
    if (!form || select.tagName !== "SELECT") return;
    if (form.requestSubmit) form.requestSubmit(); else form.submit();
  });
})();
