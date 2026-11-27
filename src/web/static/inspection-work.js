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

  // Развёрнутая формулировка закреплённого издания — рядом с пунктом,
  // поверх прокручиваемой таблицы. Делегирование работает и в панели проверки.
  var point = null, tip = null, closeTimer = null;
  function hideGuidance() {
    clearTimeout(closeTimer);
    if (point) point.removeAttribute("aria-describedby");
    point = null;
    if (tip) tip.hidden = true;
  }
  function showGuidance(button) {
    clearTimeout(closeTimer);
    if (!tip) {
      tip = document.createElement("div");
      tip.id = "technical-guidance-tooltip";
      tip.className = "popover technical-guidance";
      tip.setAttribute("role", "tooltip");
      tip.addEventListener("pointerenter", function () { clearTimeout(closeTimer); });
      tip.addEventListener("pointerleave", function () { closeTimer = setTimeout(hideGuidance, 100); });
      document.body.appendChild(tip);
    }
    if (point && point !== button) point.removeAttribute("aria-describedby");
    point = button;
    tip.textContent = "";
    var title = document.createElement("strong"), text = document.createElement("p");
    title.textContent = button.dataset.technicalTitle;
    text.textContent = button.dataset.technicalGuidance;
    tip.appendChild(title); tip.appendChild(text);
    tip.hidden = false;
    button.setAttribute("aria-describedby", tip.id);
    var rect = button.getBoundingClientRect(), size = tip.getBoundingClientRect();
    var left = Math.max(12, Math.min(rect.left, innerWidth - size.width - 12));
    var top = rect.bottom + 8;
    if (top + size.height > innerHeight - 12) top = Math.max(12, rect.top - size.height - 8);
    tip.style.left = left + "px";
    tip.style.top = top + "px";
  }
  function pointOf(target) {
    return target.closest && target.closest("[data-technical-guidance]");
  }
  document.addEventListener("pointerover", function (event) {
    var button = pointOf(event.target);
    if (button) showGuidance(button);
  });
  document.addEventListener("pointerout", function (event) {
    var button = pointOf(event.target), next = event.relatedTarget;
    if (button && !(next && (button.contains(next) || (tip && tip.contains(next))))) {
      closeTimer = setTimeout(hideGuidance, 100);
    }
  });
  document.addEventListener("focusin", function (event) {
    var button = pointOf(event.target);
    if (button) showGuidance(button);
  });
  document.addEventListener("focusout", function (event) {
    if (pointOf(event.target)) hideGuidance();
  });
  document.addEventListener("click", function (event) {
    var button = pointOf(event.target);
    if (button) showGuidance(button);
    else if (!(tip && tip.contains(event.target))) hideGuidance();
  });
  document.addEventListener("keydown", function (event) { if (event.key === "Escape") hideGuidance(); });
  document.addEventListener("scroll", function (event) {
    if (tip && !tip.contains(event.target)) hideGuidance();
  }, true);
})();
