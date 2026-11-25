// Прямое добавление файла через существующую форму, в том числе в панели проверки.
(function () {
  "use strict";
  if (window.decimusWorkReady) return;
  window.decimusWorkReady = true;
  document.documentElement.classList.add("work-enhanced");
  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest("[data-work-choose]");
    if (!button) return;
    var input = button.form.querySelector("input[type=file]");
    input.value = "";
    input.click();
  });
  document.addEventListener("change", function (event) {
    var input = event.target;
    if (!input.matches || !input.matches("[data-work-upload] input[type=file]")) return;
    if (!input.files || !input.files.length) return;
    var form = input.form;
    form.querySelector("[data-work-status]").textContent = form.dataset.workPending + " " + input.files[0].name;
    form.requestSubmit();
  });
})();
