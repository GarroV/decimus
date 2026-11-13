// Ключи доступа (WebAuthn, D463, D485, D720): вход ключом на форме входа (и на «Подтвердите
// вход»: подтверждение ключом, а у ролей с отпечатком на каждом входе — сохранение его), сохранение
// Touch ID в браузере после входа. Параметры и ответы — JSON, номера и вызов — base64url; браузеры без
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
  var TRIED_KEY = "decimus.passkey.tried";
  var LOGIN_TRIED_KEY = "decimus.passkey.login-tried";

  function storageGet(key) {
    try { return window.localStorage.getItem(key) === "1"; } catch (e) { return false; }
  }

  function storageValue(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
  }

  function storageSetValue(key, value) {
    try { window.localStorage.setItem(key, value); } catch (e) { /* без метки — только без автозапуска */ }
  }

  function storageSet(key) { storageSetValue(key, "1"); }

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
    if (!button) return;
    var origin = root.getAttribute("data-passkey-origin");
    if (origin && new URL(origin).origin !== window.location.origin) {
      button.disabled = true;
      show(root, root.getAttribute("data-msg-origin") || "");
      var canonical = root.querySelector("[data-passkey-origin-link]");
      if (canonical) canonical.hidden = false;
      return;
    }
    if (guardUnsupported(root, button)) return;
    var busy = false;
    var createUrl = root.getAttribute("data-create-url");
    // D720: ключ здесь уже есть (метка и ключи у человека) — подтверждаем им; иначе, если страница
    // это позволяет (у учётки нет ни одного способа), СОХРАНЯЕМ отпечаток сразу.
    var useExisting = storageGet(HERE_KEY) && root.hasAttribute("data-has-keys");

    function saveHere(auto) {
      if (busy) return;
      busy = true;
      hide(root);
      postJson(root.getAttribute("data-create-options-url"))
        .then(function (opts) {
          if (!opts.ok) throw Object.assign(new Error("options"), { status: opts.status, data: opts.data });
          return navigator.credentials.create({ publicKey: creationOptions(opts.data) });
        })
        .then(function (cred) {
          return postJson(createUrl, { name: deviceName(), credential: encodeCreated(cred) });
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
          throw new Error("create");
        })
        .catch(function (err) {
          busy = false;
          // Ключ с этого устройства уже есть (iCloud, другой профиль): метка потерялась —
          // подтверждаем им.
          if (err && err.name === "InvalidStateError" && root.hasAttribute("data-has-keys")) {
            storageSet(HERE_KEY);
            useExisting = true;
            run(auto);
            return;
          }
          if (err && err.status === 401 && err.data && err.data.error === "expired") {
            window.location.href = err.data.login || window.location.pathname;
            return;
          }
          show(root, root.getAttribute("data-msg-create-failed") || root.getAttribute("data-msg-failed") || "");
        });
    }

    // Отказ автоматического окна тоже объясняется: иначе человек остаётся на немом экране.
    function run(auto) {
      if (busy) return;
      busy = true;
      hide(root);
      postJson(root.getAttribute("data-options-url"))
        .then(function (opts) {
          if (!opts.ok) throw Object.assign(new Error("options"), { status: opts.status, data: opts.data });
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
        .catch(function (err) {
          busy = false;
          if (err && err.status === 401 && err.data && err.data.error === "expired") {
            window.location.href = err.data.login || window.location.pathname;
            return;
          }
          show(root, root.getAttribute("data-msg-failed") || "");
        });
    }

    function go(auto) { if (useExisting || !createUrl) run(auto); else saveHere(auto); }

    button.addEventListener("click", function () { go(false); });
    // Автозапуск — в браузере, где ключ уже был (метка): подтверждение; где ключа нет и страница
    // позволяет сохранить его (D720): сохранение. Иначе страница ведёт с поля кода, а кнопка
    // ключа остаётся запасной.
    if (useExisting || createUrl) {
      if (root.hasAttribute("data-passkey-autostart")) {
        var attempt = root.getAttribute("data-attempt");
        if (attempt && storageValue(LOGIN_TRIED_KEY) === attempt) {
          show(root, root.getAttribute(createUrl && !useExisting ? "data-msg-create-failed" : "data-msg-failed") || "");
        } else {
          if (attempt) storageSetValue(LOGIN_TRIED_KEY, attempt);
          go(true);
        }
      }
    } else {
      var methods = root.parentNode;
      if (methods && methods.classList && methods.classList.contains("login__methods")) methods.classList.add("login__methods--code-first");
    }
  }

  // --- сохранить Touch ID в этом браузере после входа (D485) ----------------------------
  // Браузер без метки «ключ тут есть» после входа паролем или Google сам просит у устройства
  // Touch ID и создаёт ключ — без вопроса и кнопки. Если окно открыть не дали (Safari требует
  // жеста) или его закрыли — тогда и только тогда показывается одна строка, клик по ней
  // повторяет попытку. Автопопытка одна на вход (номер сессии в localStorage): отказ не
  // дёргает человека на каждой странице, повтор — при следующем входе.
  function initHere(root) {
    if (!supported || storageGet(HERE_KEY)) return;
    var session = root.getAttribute("data-session") || "";
    var busy = false;
    var toSecurity = function () { window.location.href = root.getAttribute("data-security-url"); };

    function attempt(auto) {
      if (busy) return;
      busy = true;
      postJson(root.getAttribute("data-options-url"))
        .then(function (opts) {
          if (!opts.ok) throw Object.assign(new Error("options"), { refused: true });
          return navigator.credentials.create({ publicKey: creationOptions(opts.data) });
        })
        .then(function (cred) {
          return postJson(root.getAttribute("data-register-url"), {
            name: deviceName(),
            credential: encodeCreated(cred),
          });
        })
        .then(function (res) {
          if (!res.ok) throw Object.assign(new Error("register"), { refused: true });
          storageSet(HERE_KEY);
          root.hidden = true;
        })
        .catch(function (err) {
          busy = false;
          var name = err && err.name;
          // Ключ с этого устройства уже есть (InvalidStateError): метка просто потерялась.
          if (name === "InvalidStateError") { storageSet(HERE_KEY); root.hidden = true; return; }
          // Отказ сервера (окно подключения, лимит) по клику ведёт на «Вход и защиту».
          if (err && err.refused && !auto) { toSecurity(); return; }
          root.hidden = false;
        });
    }

    root.addEventListener("click", function () { attempt(false); });
    if (storageValue(TRIED_KEY) === session) {
      root.hidden = false;
      return;
    }
    storageSetValue(TRIED_KEY, session);
    attempt(true);
  }

  function init() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-passkey-here]"), initHere);
    Array.prototype.forEach.call(document.querySelectorAll("[data-passkey-login]"), initLogin);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
