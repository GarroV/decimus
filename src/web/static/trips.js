// Поездки: строки посещений, поиск точек и переход к выбранному дню.
(function () {
  "use strict";
  if (window.decimusTrips) return;
  window.decimusTrips = true;

  function filterUnits(picker, countryChanged) {
    var select = picker.querySelector("[data-trip-unit-select]");
    var search = picker.querySelector("[data-trip-unit-search]");
    var form = picker.closest("[data-trip-create]");
    var country = form ? form.elements.country.value : select.dataset.country;
    var query = search.value.trim().toLocaleLowerCase();
    Array.from(select.options).forEach(function (option) {
      var wrongCountry = country && option.dataset.country !== country;
      if (countryChanged && option.value && option.selected && wrongCountry) select.value = "";
      option.hidden = !!option.value && (wrongCountry || !option.textContent.toLocaleLowerCase().includes(query));
      option.disabled = !!option.value && !!wrongCountry;
    });
  }

  function init() {
    document.querySelectorAll("[data-trip-unit-picker]").forEach(function (picker) {
      if (picker.dataset.ready) return;
      picker.dataset.ready = "1";
      filterUnits(picker, false);
    });
    document.querySelectorAll("[data-trip-selected-day]:not([data-scrolled])").forEach(function (day) {
      day.dataset.scrolled = "1";
      requestAnimationFrame(function () { day.scrollIntoView({ block: "start" }); });
    });
  }

  document.addEventListener("input", function (event) {
    if (event.target.matches("[data-trip-unit-search]")) {
      filterUnits(event.target.closest("[data-trip-unit-picker]"), false);
    }
  });
  document.addEventListener("change", function (event) {
    var form = event.target.closest("[data-trip-create]");
    if (!form) return;
    if (event.target.name === "country") {
      form.querySelectorAll("[data-trip-unit-picker]").forEach(function (picker) { filterUnits(picker, true); });
    }
  });
  document.addEventListener("click", function (event) {
    var date = event.target.closest("input[data-trip-date]");
    if (date && typeof date.showPicker === "function") {
      try {
        date.showPicker();
        event.preventDefault();
      } catch (_) { /* Старый браузер сохраняет обычный ввод и системный значок. */ }
    }
    var add = event.target.closest("[data-trip-visit-add]");
    var remove = event.target.closest("[data-trip-visit-remove]");
    if (add) {
      var form = add.closest("[data-trip-create]");
      var rows = form.querySelector("[data-trip-visits]");
      if (rows.children.length >= Number(form.dataset.maxSteps)) return;
      var row = form.querySelector("[data-trip-visit-template]").content.cloneNode(true);
      var day = row.querySelector('[name="visit_day"]');
      var previous = rows.querySelector('[data-trip-visit]:last-child [name="visit_day"]');
      day.value = (previous && previous.value) || form.elements.from.value;
      rows.appendChild(row);
      init();
      rows.lastElementChild.querySelector("input").focus();
    }
    if (remove) remove.closest("[data-trip-visit]").remove();
  });
  new MutationObserver(init).observe(document.body, { childList: true, subtree: true });
  init();
})();
