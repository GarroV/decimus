/* Мини-апп обхода: кадры (D312) — сжать на телефоне, отправить, показать.
 *
 * Камера в WebView телеграма открывается только полем выбора файла:
 * getUserMedia там не работает. Поле одно и без `capture` (D422): телефон
 * сам предлагает «Сделать снимок / Медиатека / Выбрать файлы», сразу несколько кадров.
 *
 * Снимок сжимается здесь же, до 1600 px по длинной стороне: кадр с телефона —
 * 3–8 МБ, на мобильной связи в подвале пиццерии это минуты, а для отчёта
 * хватает и полумегабайта. Поворот по EXIF браузер применяет сам, когда
 * рисует картинку, поэтому после перекодирования кадр не ложится на бок.
 *
 * Качество — автоматом по связи, без настройки (D442): хорошая сеть — как выше,
 * слабая — кадр меньше и жмётся сильнее. Связь читается из `navigator.connection`
 * (там, где он есть), а также из длительности последних отправок: на iOS и в
 * части WebView интерфейса нет. Берётся худшее из двух.
 * Кадр, который не ушёл из-за сети, не теряется: им занят `walk-offline.js`.
 */
(function () {
  "use strict";

  var W = window.DecimusWalk;
  var views = {};

  /** Три ступени: хорошая сеть — как всегда, слабая и совсем слабая — меньше и жёстче. */
  var PROFILES = [
    { name: "good", maxSide: 1600, quality: 0.82 },
    { name: "weak", maxSide: 1100, quality: 0.62 },
    { name: "poor", maxSide: 800, quality: 0.5 },
  ];
  var WEAK_DOWNLINK_MBPS = 1.5;
  var POOR_DOWNLINK_MBPS = 0.4;
  var WEAK_TYPES = ["3g"];
  var POOR_TYPES = ["slow-2g", "2g"];
  var WEAK_KBPS = 1200;
  var POOR_KBPS = 300;
  var SAMPLES_KEPT = 5;
  var SAMPLE_MIN_BYTES = 15 * 1024;
  var SAMPLE_TTL_MS = 10 * 60 * 1000;
  var SAMPLES_KEY = "decimus_walk_net";
  var UPLOAD_TIMEOUT_MS = 60 * 1000;
  /** Ответы, после которых кадр стоит отправить позже: прокси или сервер не дотянулись. */
  var RETRY_STATUSES = [408, 425, 429, 500, 502, 503, 504];

  /** Ступень по `navigator.connection`; нет интерфейса — 0 (ничего не известно). */
  function rankByConnection() {
    var c = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
    if (!c) return 0;
    var r = c.saveData ? 1 : 0;
    if (POOR_TYPES.indexOf(c.effectiveType) !== -1) r = 2;
    else if (WEAK_TYPES.indexOf(c.effectiveType) !== -1) r = Math.max(r, 1);
    if (typeof c.downlink === "number" && c.downlink > 0) {
      if (c.downlink < POOR_DOWNLINK_MBPS) r = 2;
      else if (c.downlink < WEAK_DOWNLINK_MBPS) r = Math.max(r, 1);
    }
    return r;
  }

  function samples() {
    var list = W.local.get(SAMPLES_KEY);
    var now = Date.now();
    return (Array.isArray(list) ? list : []).filter(function (s) {
      return s && s.kbps > 0 && now - s.at < SAMPLE_TTL_MS;
    });
  }

  /** Ступень по скорости последних отправок: медиана килобит в секунду. */
  function rankBySamples() {
    var speeds = samples().map(function (s) { return s.kbps; }).sort(function (a, b) { return a - b; });
    if (!speeds.length) return 0;
    var mid = speeds[Math.floor(speeds.length / 2)];
    return mid < POOR_KBPS ? 2 : mid < WEAK_KBPS ? 1 : 0;
  }

  /** Запомнить, как быстро ушёл кадр (или не ушёл за срок). Мелочь не меряем: там задержка, не скорость. */
  function note(bytes, ms) {
    if (bytes < SAMPLE_MIN_BYTES || ms <= 0) return;
    var list = samples();
    list.push({ kbps: (bytes * 8) / ms, at: Date.now() });
    W.local.set(SAMPLES_KEY, list.slice(-SAMPLES_KEPT));
  }

  /** Сейчас нужная ступень: `{ name, maxSide, quality }`. */
  function profile() {
    return PROFILES[Math.max(rankByConnection(), rankBySamples())];
  }

  function failure(message, retryable, status) {
    var err = new Error(message);
    err.retryable = retryable;
    err.status = status;
    return err;
  }

  /** Отказ «нет сети» без обращения к серверу: кадр сразу уходит в очередь. */
  function offline() { return failure(W.tx("walk.err.network"), true, 0); }

  function decode(file) {
    if (window.createImageBitmap) {
      return createImageBitmap(file, { imageOrientation: "from-image" }).catch(function () {
        return viaImage(file);
      });
    }
    return viaImage(file);
  }

  function viaImage(file) {
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(file);
      var img = new Image();
      img.onload = function () { resolve(img); };
      img.onerror = function () { URL.revokeObjectURL(url); reject(new Error("decode")); };
      img.src = url;
    });
  }

  /** Файл с телефона → JPEG по ступени связи (`profile()`). Не разобрался — отказ. */
  function compress(file, chosen) {
    var use = chosen || profile();
    return decode(file).then(function (img) {
      var w = img.width;
      var h = img.height;
      var k = Math.min(1, use.maxSide / Math.max(w, h));
      var canvas = document.createElement("canvas");
      canvas.width = Math.round(w * k);
      canvas.height = Math.round(h * k);
      canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
      return new Promise(function (resolve, reject) {
        canvas.toBlob(function (blob) {
          if (blob) resolve(blob); else reject(new Error("encode"));
        }, "image/jpeg", use.quality);
      });
    });
  }

  /** Отправить кадр. Ответ — ссылка `walk:…`. Отказ — Error с текстом для аудитора;
   *  `retryable` — не дошло из-за сети или сервер не дотянулся: кадр стоит отправить позже. */
  function upload(blob) {
    var ctl = window.AbortController ? new AbortController() : null;
    var timer = ctl ? setTimeout(function () { ctl.abort(); }, UPLOAD_TIMEOUT_MS) : null;
    var started = Date.now();
    return W.post(W.urls.photo, blob, "image/jpeg", ctl && ctl.signal).then(function (res) {
      clearTimeout(timer);
      if (res.ok && res.body && res.body.ref) {
        note(blob.size, Date.now() - started);
        return res.body.ref;
      }
      if (RETRY_STATUSES.indexOf(res.status) !== -1) throw failure(W.tx("walk.err.network"), true, res.status);
      var msg = res.body && res.body.message;
      throw failure(msg || W.tx("walk.err.photo_bad"), false, res.status);
    }, function (err) {
      clearTimeout(timer);
      // Оборвали по сроку — связь слабая, следующие кадры сожмём сильнее.
      if (err && err.name === "AbortError") note(blob.size, UPLOAD_TIMEOUT_MS);
      throw failure(W.tx("walk.err.network"), true, 0);
    });
  }

  /** Адрес картинки для показа: кадр мини-аппа — с сервера, один раз за сессию. */
  function view(ref) {
    if (views[ref]) return views[ref];
    views[ref] = W.post(W.urls.photoView, { ref: ref }).then(function (res) {
      if (!res.ok || !(res.body instanceof Blob)) throw new Error("view");
      return URL.createObjectURL(res.body);
    });
    views[ref].catch(function () { delete views[ref]; });
    return views[ref];
  }

  /** Запомнить уже показанный локально кадр, чтобы не тянуть его с сервера. */
  function remember(ref, url) { views[ref] = Promise.resolve(url); }

  /** Кнопка выбора кадров. Поле без `capture`: телефон сам предлагает «Снять / Медиатека / Файлы»
   *  (D422). `onFiles` получает список File. */
  function picker(label, onFiles) {
    var wrap = W.hinted(W.el("label", "walk-pick walk-pick--camera"), "photo");
    var input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.multiple = true;
    input.className = "walk-pick__input";
    input.addEventListener("change", function () {
      var files = Array.prototype.slice.call(input.files || []);
      input.value = "";
      if (files.length) onFiles(files);
    });
    wrap.appendChild(input);
    wrap.appendChild(W.icon("camera", "walk-pick__icon"));
    wrap.appendChild(W.el("span", "walk-pick__label", label));
    return wrap;
  }

  /** Превью кадра: картинка или заглушка «фото из чата». */
  function thumb(photo) {
    var box = W.el("span", "walk-thumb");
    if (photo.url) {
      var img = W.el("img", "walk-thumb__img");
      img.alt = "";
      img.src = photo.url;
      box.appendChild(img);
    } else if (photo.own) {
      view(photo.ref).then(function (url) {
        var img = W.el("img", "walk-thumb__img");
        img.alt = "";
        img.src = url;
        box.textContent = "";
        box.appendChild(img);
      }, function () { box.classList.add("is-missing"); });
    } else {
      box.classList.add("is-chat");
      box.appendChild(W.el("span", "walk-thumb__note", W.tx("walk.photo.chat")));
    }
    return box;
  }

  /**
   * Кадры записи с их состоянием и одна кнопка «Фото нарушения».
   * `hero` — кадров ещё нет и снимок — первое действие формы (D330): крупная плитка.
   */
  function block(photos, on) {
    var tx = W.tx;
    var box = W.el("div", "walk-photos");
    if (photos.length) {
      var strip = W.el("div", "walk-strip");
      photos.forEach(function (p) {
        var cell = W.el("div", "walk-strip__cell is-" + (p.state || "done"));
        cell.appendChild(thumb(p));
        if (p.state === "uploading") cell.appendChild(W.el("span", "walk-strip__state", tx("walk.photo.uploading")));
        if (p.state === "waiting") cell.appendChild(W.el("span", "walk-strip__state walk-strip__state--wait", tx("walk.photo.waiting")));
        if (p.state === "failed") {
          cell.appendChild(W.button("walk-strip__retry", tx("walk.photo.failed"), function () { on.onRetry(p); }));
        }
        var x = W.button("walk-strip__remove", "✕", function () { on.onRemove(p); });
        x.setAttribute("aria-label", tx("walk.photo.remove"));
        cell.appendChild(x);
        strip.appendChild(cell);
      });
      box.appendChild(strip);
    }
    var one = picker(photos.length ? tx("walk.photo.more") : tx("walk.photo.hero"), on.onFiles);
    if (on.hero) one.classList.add("walk-pick--hero");
    box.appendChild(one);
    return box;
  }

  W.photo = { compress: compress, upload: upload, profile: profile, offline: offline, view: view, remember: remember, picker: picker, thumb: thumb, block: block };
})();
