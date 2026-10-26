/* Мини-апп обхода: свой голосовой ввод у текстовых полей (D652).
 *
 * Рядом с полем «Что не так» и комментарием — кнопка «Надиктовать». Нажатие
 * начинает запись с микрофона телефона (идёт таймер и «Стоп»), второе нажатие —
 * заканчивает; запись уходит в `/tg/walk/transcribe`, текст, расшифрованный той
 * же моделью, что и голосовые в чате, ДОПИСЫВАЕТСЯ в поле. Аудитор видит его до
 * сохранения и правит: сама запись остаётся за обычной «Сохранить» (модель
 * предлагает, фиксирует человек).
 *
 * Кнопки нет, когда у веб-вью нет микрофона или записи (`getUserMedia`,
 * `MediaRecorder`): остаётся диктовка клавиатуры. Отказ в доступе — строка
 * в уведомлении, не `alert()`. Запись длится не дольше `LIMIT_SEC`; закрытие
 * формы или экрана прерывает запись и выбрасывает её, микрофон отпускается.
 */
(function () {
  "use strict";

  var W = (window.DecimusWalk = window.DecimusWalk || {});

  var LIMIT_SEC = 60;
  /* Короче этого — случайное нажатие: сервер получил бы пустой звук. */
  var MIN_BYTES = 800;
  var TICK_MS = 250;
  var MIMES = ["audio/webm;codecs=opus", "audio/mp4"];

  /* Идущие записи: форма при закрытии прерывает их все. */
  var live = [];

  function supported() {
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
  }

  function pickMime() {
    if (!window.MediaRecorder.isTypeSupported) return "";
    for (var i = 0; i < MIMES.length; i++) {
      if (window.MediaRecorder.isTypeSupported(MIMES[i])) return MIMES[i];
    }
    return "";
  }

  function clock(sec) {
    var s = Math.floor(sec);
    return Math.floor(s / 60) + ":" + (s % 60 < 10 ? "0" : "") + (s % 60);
  }

  W.voice = {
    /** Прервать все идущие записи, ничего не отправляя. */
    cancelAll: function () { live.slice().forEach(function (stop) { stop(true); }); },
  };

  /**
   * Кнопка записи для поля `area`. Возвращает узел, который кладут сразу после
   * поля, или null, когда записать нечем или поле закрыто для правки.
   *
   * `onText(text, wasEmpty)` вызывается после того, как текст лёг в поле;
   * `wasEmpty` — поле было пустым до записи.
   */
  W.voiceBar = function (area, onText) {
    if (!supported() || !W.urls.voice || area.disabled) return null;

    var el = W.el;
    var bar = el("div", "walk-voice");
    var go = W.button("walk-link walk-voice__go", "");
    var error = el("p", "walk-form__error walk-voice__error");
    error.setAttribute("role", "alert");
    error.hidden = true;
    bar.appendChild(go);
    bar.appendChild(error);

    var state = "idle"; // idle | starting | recording | busy
    var session = null;

    function label() {
      go.textContent = "";
      go.classList.toggle("is-rec", state === "recording");
      go.disabled = state === "starting" || state === "busy";
      if (state === "recording") {
        go.appendChild(el("span", "walk-voice__dot"));
        go.appendChild(document.createTextNode(W.tx("walk.voice.stop", { time: clock(session.seconds()) })));
      } else if (state === "busy") {
        go.appendChild(document.createTextNode(W.tx("walk.voice.busy")));
      } else {
        go.appendChild(W.icon("mic", "walk-voice__icon"));
        go.appendChild(document.createTextNode(W.tx("walk.voice.start")));
      }
    }

    function fail(message) {
      error.textContent = message;
      error.hidden = false;
      W.haptic("error");
    }

    function release(stream) {
      stream.getTracks().forEach(function (t) { try { t.stop(); } catch (e) { /* уже закрыт */ } });
    }

    function land(text) {
      var wasEmpty = !area.value.trim();
      var cur = area.value;
      area.value = cur && !/\s$/.test(cur) ? cur + " " + text : cur + text;
      area.dispatchEvent(new Event("input", { bubbles: true }));
      W.haptic("success");
      if (onText) onText(text, wasEmpty);
    }

    function send(blob) {
      state = "busy";
      label();
      W.post(W.urls.voice, blob, blob.type || "application/octet-stream").then(function (res) {
        if (!res.ok || !res.body || typeof res.body.text !== "string") {
          throw new Error((res.body && res.body.message) || W.tx("walk.error"));
        }
        land(res.body.text);
      }).catch(function (e) {
        fail(e && e.message && e.message !== "Failed to fetch" ? e.message : W.tx("walk.err.network"));
      }).then(function () {
        state = "idle";
        label();
      });
    }

    function begin() {
      if (state !== "idle") return;
      state = "starting";
      error.hidden = true;
      label();
      navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
        var mime = pickMime();
        var rec;
        try {
          rec = mime ? new window.MediaRecorder(stream, { mimeType: mime }) : new window.MediaRecorder(stream);
        } catch (e) {
          release(stream);
          throw e;
        }
        var chunks = [];
        var started = Date.now();
        var discard = false;
        var timer = null;
        var self = {
          seconds: function () { return (Date.now() - started) / 1000; },
        };
        function stop(drop) {
          if (drop) discard = true;
          if (rec.state !== "inactive") rec.stop();
        }
        function done() {
          window.clearInterval(timer);
          window.removeEventListener("pagehide", onHide);
          document.removeEventListener("visibilitychange", onVis);
          var at = live.indexOf(stop);
          if (at !== -1) live.splice(at, 1);
          release(stream); // индикатор микрофона гаснет сразу
          session = null;
          var blob = new Blob(chunks, { type: rec.mimeType || mime || "audio/webm" });
          if (discard || blob.size < MIN_BYTES) {
            state = "idle";
            label();
            return;
          }
          send(blob);
        }
        function onHide() { stop(true); }
        function onVis() { if (document.visibilityState === "hidden") stop(true); }
        rec.addEventListener("dataavailable", function (ev) { if (ev.data && ev.data.size) chunks.push(ev.data); });
        rec.addEventListener("stop", done);
        rec.addEventListener("error", function () { stop(true); fail(W.tx("walk.err.voice")); });
        self.stop = stop;
        session = self;
        live.push(stop);
        window.addEventListener("pagehide", onHide);
        document.addEventListener("visibilitychange", onVis);
        timer = window.setInterval(function () {
          // Поле пропало с экрана (форма перерисована или закрыта) — запись не нужна.
          if (!bar.isConnected) { stop(true); return; }
          if (self.seconds() >= LIMIT_SEC) { stop(false); return; }
          label();
        }, TICK_MS);
        state = "recording";
        rec.start();
        W.haptic();
        label();
      }).catch(function (e) {
        state = "idle";
        label();
        var name = e && e.name;
        if (name === "NotAllowedError" || name === "SecurityError" || name === "NotFoundError" ||
            name === "PermissionDeniedError" || name === "NotReadableError") {
          W.toast(W.tx("walk.voice.denied"), "err");
          W.haptic("error");
        } else {
          fail(W.tx("walk.voice.denied"));
        }
      });
    }

    go.addEventListener("click", function () {
      if (state === "recording" && session) session.stop(false);
      else begin();
    });
    label();
    return bar;
  };
})();
