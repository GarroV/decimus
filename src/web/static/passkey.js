// Ключи доступа (WebAuthn, D463): вход ключом на «Подтвердите вход» и добавление ключа
// на «Вход и защита». Параметры и ответы — JSON, номера и вызов — base64url; браузеры без
// `PublicKeyCredential.parse…FromJSON` обслуживаются ручным разбором, поэтому работает
// и в Safari 16, и в Chrome. Без WebAuthn (встроенный браузер Telegram) — подсказка
// «откройте в Safari или Chrome»; страница остаётся рабочей через код.
(function () {
  "use strict";

  var supported = !!(window.PublicKeyCredential && navigator.credentials &&
    typeof navigator.credentials.create === "function");

  // Ключ живёт там, где создан: в другом браузере окно ключа показало бы QR-код. Поэтому
  // браузер помнит, что ключ тут есть (создан или вошли им), и без метки окно само не
  // открывается. Хранилище бывает закрыто (приватное окно) — любая осечка читается как «нет».
  var HERE_KEY = "decimus.passkey.here";
  var DISMISS_KEY = "decimus.passkey.dismissed";

  function storageGet(key) {
    try { return window.localStorage.getItem(key) === "1"; } catch (e) { return false; }
  }

  function storageSet(key) {
    try { window.localStorage.setItem(key, "1"); } catch (e) { /* без метки — только без автозапуска */ }
  }

  // «Chrome · Mac»: имя ключа по браузеру и системе, чтобы не спрашивать его у человека.
  function deviceName() {
    var ua = navigator.userAgent || "";
    var browser = /Edg\//.test(ua) ? "Edge" : /OPR\//.test(ua) ? "Opera"
      : /Firefox\//.test(ua) ? "Firefox" : /Chrome\//.test(ua) ? "Chrome"
      : /Safari\//.test(ua) ? "Safari" : "Browser";
    var os = /iPhone/.test(ua) ? "iPhone" : /iPad/.test(ua) ? "iPad" : /Android/.test(ua) ? "Android"
      : /Mac/.test(ua) ? "Mac" : /Windows/.test(ua) ? "Windows" : /Linux/.test(ua) ? "Linux" : "";
    return os ? browser + " \u00b7 " + os : browser;
  }

  function fromB64(text) {
    var pad = "=".repeat((4 - (text.length % 4)) % 4);
    var raw = atob((text + pad).replace(/-/g, "+").replace(/_/g, "/"));
    var out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out.buffer;
  }

  function toB64(buffer) {
    var bytes = new Uint8Array(buffer);
    var raw = "";
    for (var i = 0; i < bytes.length; i++) raw += String.fromCharCode(bytes[i]);
    return btoa(raw).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function descriptors(list) {
    return (list || []).map(function (d) {
      return Object.assign({}, d, { id: fromB64(d.id) });
    });
  }

  function creationOptions(json) {
    var o = Object.assign({}, json);
    o.challenge = fromB64(json.challenge);
    o.user = Object.assign({}, json.user, { id: fromB64(json.user.id) });
    o.excludeCredentials = descriptors(json.excludeCredentials);
    return o;
  }

  function requestOptions(json) {
    var o = Object.assign({}, json);
    o.challenge = fromB64(json.challenge);
    o.allowCredentials = descriptors(json.allowCredentials);
    return o;
  }

  function encodeCreated(cred) {
    var r = cred.response;
    return {
      id: cred.id,
      rawId: toB64(cred.rawId),
      type: cred.type,
      response: {
        clientDataJSON: toB64(r.clientDataJSON),
        attestationObject: toB64(r.attestationObject),
        transports: typeof r.getTransports === "function" ? r.getTransports() : [],
      },
      clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {},
      authenticatorAttachment: cred.authenticatorAttachment || undefined,
    };
  }

  function encodeAsserted(cred) {
    var r = cred.response;
    return {
      id: cred.id,
      rawId: toB64(cred.rawId),
      type: cred.type,
      response: {
        clientDataJSON: toB64(r.clientDataJSON),
        authenticatorData: toB64(r.authenticatorData),
        signature: toB64(r.signature),
        userHandle: r.userHandle ? toB64(r.userHandle) : undefined,
      },
      clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {},
    };
  }

  function postJson(url, body) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body === undefined ? {} : body),
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        return { ok: res.ok, status: res.status, data: data };
      });
    });
  }

  function show(root, text) {
    var box = root.querySelector("[data-passkey-message]");
    var line = root.querySelector("[data-passkey-message-text]");
    if (!box || !line) return;
    line.textContent = text;
    box.hidden = false;
  }

  function hide(root) {
    var box = root.querySelector("[data-passkey-message]");
    if (box) box.hidden = true;
  }

  function guardUnsupported(root, button) {
    if (supported) return false;
    button.disabled = true;
    show(root, root.getAttribute("data-msg-unavailable") || "");
    return true;
  }

  // --- вход ключом на «Подтвердите вход» ---------------------------------------------
  function initLogin(root) {
    var button = root.querySelector("[data-passkey-button]");
    if (!button || guardUnsupported(root, button)) return;
    var busy = false;

    // `auto` — запуск при открытии страницы, без нажатия: осечка тут тихая (кнопка
    // остаётся, сообщения нет). Safari и другие браузеры вправе отказать вызову без
    // жеста пользователя (NotAllowedError) — тогда человек просто нажимает кнопку.
    function run(auto) {
      if (busy) return;
      busy = true;
      hide(root);
      postJson(root.getAttribute("data-options-url"))
        .then(function (opts) {
          if (!opts.ok) throw new Error("options");
          return navigator.credentials.get({ publicKey: requestOptions(opts.data) });
        })
        .then(function (cred) {
          return postJson(root.getAttribute("data-verify-url"), encodeAsserted(cred));
        })
        .then(function (res) {
          if (res.ok && res.data && res.data.redirect) {
            storageSet(HERE_KEY);
            window.location.href = res.data.redirect;
            return;
          }
          if (res.status === 401 && res.data && res.data.error === "expired") {
            window.location.href = res.data.login || window.location.pathname;
            return;
          }
          throw new Error("verify");
        })
        .catch(function () {
          busy = false;
          if (!auto) show(root, root.getAttribute("data-msg-failed") || "");
        });
    }

    button.addEventListener("click", function () { run(false); });
    // Автозапуск — только в браузере, где ключ уже был (метка). В остальных страница
    // ведёт с поля кода, а кнопка ключа остаётся запасной.
    if (storageGet(HERE_KEY)) {
      if (root.hasAttribute("data-passkey-autostart")) run(true);
    } else {
      var methods = root.parentNode;
      if (methods && methods.classList) methods.classList.add("login__methods--code-first");
    }
  }

  // --- добавление ключа на «Вход и защита» ----------------------------------------------
  function initRegister(root) {
    var button = root.querySelector("[data-passkey-button]");
    if (!button || guardUnsupported(root, button)) return;
    var busy = false;
    button.addEventListener("click", function () {
      if (busy) return;
      busy = true;
      hide(root);
      var nameField = root.querySelector("[data-passkey-name]");
      var name = nameField ? nameField.value : "";
      postJson(root.getAttribute("data-options-url"))
        .then(function (opts) {
          if (!opts.ok) throw new Error("options");
          return navigator.credentials.create({ publicKey: creationOptions(opts.data) });
        })
        .then(function (cred) {
          return postJson(root.getAttribute("data-register-url"), {
            name: name,
            credential: encodeCreated(cred),
          });
        })
        .then(function (res) {
          if (res.ok && res.data && res.data.redirect) {
            storageSet(HERE_KEY);
            window.location.href = res.data.redirect;
            return;
          }
          throw new Error("register");
        })
        .catch(function () {
          busy = false;
          show(root, root.getAttribute("data-msg-failed") || "");
        });
    });
  }

  // --- «Входить по Touch ID в этом браузере?» после входа (D485) -------------------------
  // Плашка скрыта разметкой и показывается, только если браузер поддерживает ключи, метки
  // тут нет и «Не сейчас» не нажимали. Один клик — ключ создаётся тут же, без имени.
  // Отказ сервера (окно подключения закрылось, лимит) уводит на «Вход и защиту» без шума.
  function initHere(root) {
    var button = root.querySelector("[data-passkey-here-enable]");
    var later = root.querySelector("[data-passkey-here-later]");
    if (!button || !supported || storageGet(HERE_KEY) || storageGet(DISMISS_KEY)) return;
    root.hidden = false;
    var busy = false;
    var toSecurity = function () { window.location.href = root.getAttribute("data-security-url"); };

    if (later) later.addEventListener("click", function () {
      storageSet(DISMISS_KEY);
      root.hidden = true;
    });
    button.addEventListener("click", function () {
      if (busy) return;
      busy = true;
      postJson(root.getAttribute("data-options-url"))
        .then(function (opts) {
          if (!opts.ok) { toSecurity(); return null; }
          return navigator.credentials.create({ publicKey: creationOptions(opts.data) })
            .then(function (cred) {
              return postJson(root.getAttribute("data-register-url"), {
                name: deviceName(),
                credential: encodeCreated(cred),
              });
            })
            .then(function (res) {
              if (!res.ok) { toSecurity(); return; }
              storageSet(HERE_KEY);
              root.hidden = true;
            });
        })
        .catch(function (err) {
          busy = false;
          var name = err && err.name;
          // Ключ с этого устройства уже есть (InvalidStateError): метка просто потерялась.
          if (name === "InvalidStateError") { storageSet(HERE_KEY); root.hidden = true; return; }
          // Окно закрыли или отказали (NotAllowedError): тихо, кнопка остаётся.
          if (name !== "NotAllowedError" && name !== "AbortError") toSecurity();
        });
    });
  }

  function init() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-passkey-here]"), initHere);
    Array.prototype.forEach.call(document.querySelectorAll("[data-passkey-login]"), initLogin);
    Array.prototype.forEach.call(document.querySelectorAll("[data-passkey-register]"), initRegister);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
