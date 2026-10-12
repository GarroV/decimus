/* Мини-апп обхода: кадры (D312) — сжать на телефоне, отправить, показать.
 *
 * Камера в WebView телеграма открывается только полем выбора файла:
 * getUserMedia там не работает. `capture="environment"` сразу открывает
 * заднюю камеру, поле без него — выбор из галереи, сразу несколько кадров.
 *
 * Снимок сжимается здесь же, до 1600 px по длинной стороне: кадр с телефона —
 * 3–8 МБ, на мобильной связи в подвале пиццерии это минуты, а для отчёта
 * хватает и полумегабайта. Поворот по EXIF браузер применяет сам, когда
 * рисует картинку, поэтому после перекодирования кадр не ложится на бок.
 */
(function () {
  "use strict";

  var W = window.DecimusWalk;
  var MAX_SIDE = 1600;
  var QUALITY = 0.82;
  var views = {};

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

  /** Файл с телефона → JPEG не больше MAX_SIDE. Не разобрался — отказ. */
  function compress(file) {
    return decode(file).then(function (img) {
      var w = img.width;
      var h = img.height;
      var k = Math.min(1, MAX_SIDE / Math.max(w, h));
      var canvas = document.createElement("canvas");
      canvas.width = Math.round(w * k);
      canvas.height = Math.round(h * k);
      canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
      return new Promise(function (resolve, reject) {
        canvas.toBlob(function (blob) {
          if (blob) resolve(blob); else reject(new Error("encode"));
        }, "image/jpeg", QUALITY);
      });
    });
  }

  /** Отправить кадр. Ответ — ссылка `walk:…`, отказ — текст для аудитора. */
  function upload(blob) {
    return W.post(W.urls.photo, blob, "image/jpeg").then(function (res) {
      if (res.ok && res.body && res.body.ref) return res.body.ref;
      var msg = res.body && res.body.message;
      throw new Error(msg || W.tx("walk.err.photo_bad"));
    }, function () {
      throw new Error(W.tx("walk.err.network"));
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

  /** Кнопка выбора кадров: камера или галерея. `onFiles` получает список File. */
  function picker(label, camera, onFiles) {
    var wrap = W.el("label", "walk-pick" + (camera ? " walk-pick--camera" : ""));
    var input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    if (camera) input.setAttribute("capture", "environment");
    else input.multiple = true;
    input.className = "walk-pick__input";
    input.addEventListener("change", function () {
      var files = Array.prototype.slice.call(input.files || []);
      input.value = "";
      if (files.length) onFiles(files);
    });
    wrap.appendChild(input);
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
   * Кадры записи с их состоянием и кнопки «снять / из галереи».
   * `hero` — кадров ещё нет и снимок — первое действие формы (D330): крупная
   * плитка камеры и ссылка на галерею вместо двух равных кнопок.
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
    if (on.hero) {
      var big = picker(tx("walk.photo.hero"), true, on.onFiles);
      big.classList.add("walk-pick--hero");
      big.appendChild(W.el("span", "walk-pick__sub", tx("walk.photo.hero_hint")));
      box.appendChild(big);
      var gal = picker(tx("walk.photo.gallery_link"), false, on.onFiles);
      gal.classList.add("walk-pick--link");
      box.appendChild(gal);
      return box;
    }
    var row = W.el("div", "walk-pickrow");
    row.appendChild(picker(photos.length ? tx("walk.photo.more") : tx("walk.photo.camera"), true, on.onFiles));
    row.appendChild(picker(tx("walk.photo.gallery"), false, on.onFiles));
    box.appendChild(row);
    return box;
  }

  W.photo = { compress: compress, upload: upload, view: view, remember: remember, picker: picker, thumb: thumb, block: block };
})();
