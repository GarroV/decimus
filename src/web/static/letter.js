/*
  Редактор письма партнёру (D169, #332): жирный, курсив, зачёркнутый, ссылка.

  Без библиотек: `contenteditable` и `execCommand` — то же, на чём стоит pell,
  самый маленький из известных редакторов. Набор закрыт, поэтому ни дерева
  документа, ни плагинов не нужно. Скрипт — только удобство: что именно ляжет
  в письмо, решает белый список на сервере (`src/web/letter_markup.py`), и
  разметка, собранная здесь, проходит его так же, как любая присланная.

  Без скрипта работает прежнее поле формы, поэтому всё начинается с проверки,
  что редактор вообще можно включить, — и только тогда поле прячется.
*/
(function () {
  "use strict";

  var editor = document.querySelector("[data-letter-editor]");
  var tools = document.querySelector("[data-letter-tools]");
  if (!editor || !tools || typeof document.execCommand !== "function") return;
  var field = document.getElementById(editor.getAttribute("data-field"));
  var plain = document.querySelector("[data-letter-plain]");
  var form = editor.closest("form");
  if (!field || !plain || !form) return;

  var box = tools.querySelector("[data-link-box]");
  var input = tools.querySelector("[data-link-input]");
  var note = tools.querySelector("[data-link-note]");
  var linkButton = tools.querySelector('[data-cmd="link"]');
  var SCHEME = /^(https?:\/\/\S+|mailto:\S+)$/i;
  var saved = null;

  plain.hidden = true;
  editor.hidden = false;
  tools.hidden = false;
  try {
    // Теги, а не `<span style>`: стили белый список снимает целиком.
    document.execCommand("styleWithCSS", false, false);
  } catch (e) { /* старый браузер — теги он и так ставит */ }

  function sync() { field.value = editor.innerHTML; }

  function say(text) { note.textContent = text || ""; }

  function inside(node) { return node && (node === editor || editor.contains(node)); }

  function linkAt() {
    var s = window.getSelection();
    var n = s && s.rangeCount ? s.anchorNode : null;
    while (n && n !== editor) {
      if (n.nodeName === "A") return n;
      n = n.parentNode;
    }
    return null;
  }

  function refresh() {
    var s = window.getSelection();
    if (!s || !s.rangeCount || !inside(s.anchorNode)) return;
    ["bold", "italic", "strikeThrough"].forEach(function (cmd) {
      var b = tools.querySelector('[data-cmd="' + cmd + '"]');
      var on = false;
      try { on = document.queryCommandState(cmd); } catch (e) { on = false; }
      b.setAttribute("aria-pressed", on ? "true" : "false");
    });
    linkButton.setAttribute("aria-pressed", linkAt() ? "true" : "false");
  }

  function run(cmd, value) {
    editor.focus();
    document.execCommand(cmd, false, value);
    sync();
    refresh();
  }

  function closeBox() {
    box.hidden = true;
    input.value = "";
    saved = null;
  }

  function openBox() {
    var s = window.getSelection();
    var link = linkAt();
    if (link) {
      // Повторное нажатие на ссылке снимает её: отдельной кнопки на это нет.
      var r = document.createRange();
      r.selectNodeContents(link);
      s.removeAllRanges();
      s.addRange(r);
      run("unlink");
      return;
    }
    if (!s || !s.rangeCount || s.isCollapsed || !inside(s.anchorNode)) {
      say(note.getAttribute("data-select"));
      return;
    }
    say("");
    saved = s.getRangeAt(0).cloneRange();
    box.hidden = false;
    input.focus();
  }

  function applyLink() {
    var address = input.value.trim();
    if (address && !/^[a-z][a-z0-9+.-]*:/i.test(address)) {
      address = (address.indexOf("@") > 0 && address.indexOf("/") < 0 ? "mailto:" : "https://") + address;
    }
    if (!SCHEME.test(address)) {
      say(note.getAttribute("data-bad"));
      input.focus();
      return;
    }
    var s = window.getSelection();
    editor.focus();
    if (saved) {
      s.removeAllRanges();
      s.addRange(saved);
    }
    closeBox();
    say("");
    run("createLink", address);
  }

  tools.addEventListener("mousedown", function (e) {
    // Нажатие на кнопку не должно снимать выделение в тексте письма.
    if (e.target.closest("[data-cmd]")) e.preventDefault();
  });

  tools.addEventListener("click", function (e) {
    var b = e.target.closest("[data-cmd]");
    if (b) {
      var cmd = b.getAttribute("data-cmd");
      if (cmd === "link") openBox(); else run(cmd);
      return;
    }
    if (e.target.closest("[data-link-apply]")) applyLink();
    else if (e.target.closest("[data-link-cancel]")) { closeBox(); editor.focus(); }
  });

  input.addEventListener("keydown", function (e) {
    // Enter в поле адреса ставит ссылку, а не отправляет форму письма.
    if (e.key === "Enter") { e.preventDefault(); applyLink(); }
    else if (e.key === "Escape") { e.preventDefault(); closeBox(); editor.focus(); }
  });

  editor.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.isComposing) {
      // Перевод строки, а не новый блок `<div>`: строки письма — строки текста.
      e.preventDefault();
      run("insertLineBreak");
    } else if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === "k") {
      e.preventDefault();
      openBox();
    }
  });

  editor.addEventListener("paste", function (e) {
    // Вставка — простым текстом: чужие стили и блоки всё равно снял бы
    // сервер, но человек увидел бы их здесь и решил, что так и уйдёт.
    var data = e.clipboardData && e.clipboardData.getData("text/plain");
    if (data == null) return;
    e.preventDefault();
    run("insertText", data);
  });

  editor.addEventListener("drop", function (e) { e.preventDefault(); });
  editor.addEventListener("input", sync);
  document.addEventListener("selectionchange", refresh);
  form.addEventListener("submit", sync);
  sync();
})();
