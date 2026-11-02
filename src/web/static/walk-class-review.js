/* Selected-item class proposal. Context and run/selection identity are supplied by
 * the sheet; this module never turns a coarse search candidate into a class. */
(function () {
  "use strict";
  var W = window.DecimusWalk;
  var serial = 0;

  function revision() { return "selection-" + (++serial); }
  function fresh() {
    return { key: null, revision: revision(), status: "idle", level: null,
      provisional: null, needFact: "", reason: "", message: "", manualMode: false };
  }
  function sync(state, context) {
    if (state.key === context.key) return false;
    state.key = context.key;
    state.revision = revision();
    state.status = "idle";
    state.level = null;
    state.provisional = null;
    state.needFact = "";
    state.reason = "";
    state.measurementContext = null;
    state.message = "";
    return true;
  }
  function enterManual(state, context) {
    sync(state, context);
    state.revision = revision();
    state.manualMode = true;
    state.status = "manual";
    state.level = null;
  }
  function chooseManual(state, context, level) {
    enterManual(state, context);
    if (context.levels.indexOf(level) !== -1) state.level = level;
  }
  function sameArray(a, b) {
    return Array.isArray(a) && a.length === b.length && a.every(function (v, i) { return v === b[i]; });
  }
  function validResult(result, body, context) {
    var measurement = result && result.measurement_context;
    if (body.measurement_set_id) {
      if (!measurement || measurement.set_id !== body.measurement_set_id ||
          measurement.set_revision !== body.measurement_set_revision ||
          typeof measurement.scope_hash !== "string" || !/^[a-f0-9]{64}$/.test(measurement.scope_hash)) return false;
    } else if (measurement != null) return false;
    if (!result || result.run_id !== body.run_id || result.selection_revision !== body.selection_revision ||
        result.code !== body.code || (result.zone || null) !== (body.zone || null) ||
        result.checklist_version !== body.checklist_version || !sameArray(result.photo_refs, body.photos) ||
        typeof result.facts_key !== "string" || !result.facts_key ||
        typeof result.criteria_hash !== "string" || !result.criteria_hash ||
        typeof result.clarification_hash !== "string" || !result.clarification_hash ||
        JSON.stringify(result.clarifications) !== JSON.stringify(body.clarifications) ||
        (result.need_fact !== null && typeof result.need_fact !== "string") || typeof result.reason !== "string") return false;
    if (!result.facts_from || result.facts_from.words !== !!body.words.trim() ||
        result.facts_from.confirmed_reading !== (body.reading_c !== null) ||
        result.facts_from.photos !== body.photos.length) return false;
    if (result.provisional_level !== null && context.levels.indexOf(result.provisional_level) === -1) return false;
    if (result.status === "ready") {
      return context.levels.indexOf(result.level) !== -1 && result.need_fact === "";
    }
    if (result.status === "not_established") return result.level === null && result.provisional_level === null && result.need_fact === null;
    return result.status === "needs_fact" && result.level === null && typeof result.need_fact === "string" && !!result.need_fact.trim() &&
      (result.provisional_level === null || context.levels.indexOf(result.provisional_level) !== -1);
  }
  function request(state, context, current, changed, force) {
    sync(state, context);
    // Automatic UI triggers share only the current form's identical full context.
    // Explicit checking may refresh a settled result, never duplicate an in-flight call.
    if (state.status === "pending" || (!force &&
        ["ready", "needs_fact", "not_established", "manual"].indexOf(state.status) !== -1)) return;
    state.manualMode = false;
    state.level = null;
    state.provisional = null;
    state.needFact = "";
    state.reason = "";
    state.measurementContext = null;
    state.message = "";
    state.revision = revision();
    if (context.blocked) {
      state.status = "blocked";
      state.message = context.blocked;
      changed();
      return;
    }
    var key = context.key;
    var expected = state.revision;
    var body = Object.assign({}, context.body, { selection_revision: expected });
    state.status = "pending";
    changed();
    W.post(W.urls.level, body, null, null, body.run_id).then(function (response) {
      if (state.key !== key || state.revision !== expected) return;
      // A deselected item may return later; discard its reply without leaving
      // an in-flight marker that would prevent a fresh check on reselection.
      if (!current(key)) { state.status = "idle"; return; }
      var result = response.body;
      if (!response.ok || !validResult(result, body, context)) {
        state.status = "error";
        state.message = !response.ok && result && result.message ? result.message : W.tx("walk.sheet.class_review.unavailable");
      } else {
        state.measurementContext = result.measurement_context || null;
        state.status = result.status;
        state.level = result.status === "ready" ? result.level : null;
        state.provisional = result.provisional_level;
        state.needFact = result.need_fact || "";
        state.clarificationHash = result.clarification_hash;
        state.reason = result.reason;
      }
      changed();
    }).catch(function () {
      if (state.key !== key || state.revision !== expected) return;
      // A deselected item may return later; discard its reply without leaving
      // an in-flight marker that would prevent a fresh check on reselection.
      if (!current(key)) { state.status = "idle"; return; }
      state.status = "error";
      state.message = W.tx("walk.sheet.class_review.unavailable");
      changed();
    });
  }
  W.classReview = { fresh: fresh, sync: sync, request: request, enterManual: enterManual, chooseManual: chooseManual };
})();
