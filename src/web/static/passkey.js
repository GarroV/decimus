// Ключи доступа (WebAuthn, D463): вход ключом на «Подтвердите вход» и добавление ключа
// на «Вход и защита». Параметры и ответы — JSON, номера и вызов — base64url; браузеры без
// `PublicKeyCredential.parse…FromJSON` обслуживаются ручным разбором, поэтому работает
// и в Safari 16, и в Chrome. Без WebAuthn (встроенный браузер Telegram) — подсказка
// «откройте в Safari или Chrome»; страница остаётся рабочей через код.
(function () {
  "use strict";

  var supported = !!(window.PublicKeyCredential && navigator.credentials &&
    typeof navigator.credentials.create === "function");

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
    button.addEventListener("click", function () {
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
          show(root, root.getAttribute("data-msg-failed") || "");
        });
    });
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

  function init() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-passkey-login]"), initLogin);
    Array.prototype.forEach.call(document.querySelectorAll("[data-passkey-register]"), initRegister);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
