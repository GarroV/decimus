// Кнопка «Обратная связь» (D761 п.6): окно с формой поверх страницы.
// Кнопка и окно рисует `base.html` на каждой странице вошедшего; здесь только поведение.
// Форма уходит `POST /feedback` (multipart) и получает JSON `{ok, message}` с готовым
// текстом на языке страницы. Слушатели висят на документе: переход между разделами
// (`nav.js`) подменяет `main`, а кнопка с окном остаются на месте. Адрес страницы берётся
// в момент открытия — страница под окном могла смениться без перезагрузки.
(function () {
  "use strict";

  function dialog() { return document.getElementById("feedback-dialog"); }
  function field(box, name) { return box.querySelector("[data-fb-" + name + "]"); }

  function say(box, text, bad) {
    var status = field(box, "status");
    status.textContent = text;
    status.classList.toggle("is-bad", !!bad);
  }

  function reset(box) {
    field(box, "form").reset();
    field(box, "names").textContent = "";
    say(box, "", false);
    field(box, "send").disabled = !!box.dataset.demo;
  }

  function open(trigger) {
    var box = dialog();
    if (!box || box.open) return;
    reset(box);
    field(box, "page").value = location.pathname + location.search;
    box.returnTarget = trigger;
    box.showModal();
    var first = field(box, "text");
    if (first && !first.disabled) first.focus();
  }

  function close(box) {
    if (box.open) box.close();
    if (box.returnTarget && document.contains(box.returnTarget)) box.returnTarget.focus();
  }

  function tooMany(box, input) {
    var max = parseInt(box.dataset.maxPhotos, 10);
    return input.files.length > max ? box.dataset.errMany : "";
  }

  function tooBig(box, input) {
    var max = parseInt(box.dataset.maxBytes, 10);
    for (var i = 0; i < input.files.length; i++) {
      if (input.files[i].size > max) return box.dataset.errBig;
    }
    return "";
  }

  function names(box, input) {
    var list = [];
    for (var i = 0; i < input.files.length; i++) list.push(input.files[i].name);
    field(box, "names").textContent = list.join(", ");
    var bad = tooMany(box, input) || tooBig(box, input);
    say(box, bad, !!bad);
    field(box, "send").disabled = !!bad || !!box.dataset.demo;
  }

  function submit(box, form) {
    var send = field(box, "send");
    send.disabled = true;
    say(box, box.dataset.sending, false);
    fetch(form.action, { method: "POST", body: new FormData(form), credentials: "same-origin" })
      .then(function (response) {
        return response.json().then(function (data) { return data; }, function () { return null; });
      })
      .then(function (data) {
        if (!data || typeof data.message !== "string") throw new Error("bad answer");
        say(box, data.message, !data.ok);
        if (data.ok) {
          field(box, "form").reset();
          field(box, "names").textContent = "";
          field(box, "text").disabled = true;
          send.hidden = true;
          field(box, "cancel-label").textContent = box.dataset.close;
        } else {
          send.disabled = false;
        }
      })
      .catch(function () {
        say(box, box.dataset.errNetwork, true);
        send.disabled = false;
      });
  }

  document.addEventListener("click", function (event) {
    var target = event.target;
    if (!target.closest) return;
    var trigger = target.closest("[data-feedback-open]");
    if (trigger) {
      event.preventDefault();
      open(trigger);
      return;
    }
    var box = dialog();
    if (!box || !box.open) return;
    if (target.closest("[data-fb-cancel]")) {
      event.preventDefault();
      close(box);
    } else if (target === box) {
      close(box); // клик по подложке вне окна
    }
  });

  document.addEventListener("change", function (event) {
    var input = event.target;
    var box = dialog();
    if (box && input.matches && input.matches("[data-fb-photos]")) names(box, input);
  });

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.matches || !form.matches("[data-fb-form]")) return;
    event.preventDefault();
    var box = dialog();
    if (box && !box.dataset.demo) submit(box, form);
  });

  document.addEventListener("close", function (event) {
    var box = event.target;
    if (box && box.id === "feedback-dialog") {
      field(box, "text").disabled = !!box.dataset.demo;
      field(box, "send").hidden = false;
      field(box, "cancel-label").textContent = box.dataset.cancel;
    }
  }, true);
})();
