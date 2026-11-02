"use strict";
window.addEventListener("beforeprint", () => {
  document.querySelectorAll("[data-content-controls]").forEach((element) => { element.hidden = true; });
});
window.addEventListener("afterprint", () => {
  document.querySelectorAll("[data-content-controls]").forEach((element) => { element.hidden = false; });
});
document.querySelector("[data-content-print]")?.addEventListener("click", () => { window.print(); });
