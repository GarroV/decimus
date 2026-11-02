/* Human-confirmed products and lines. Saved D0 sources are references, never counts. */
(function () {
  "use strict";
  var W = window.DecimusWalk;
  function copy(value) { return JSON.parse(JSON.stringify(value)); }
  function id() {
    var bytes = new Uint8Array(16);
    window.crypto.getRandomValues(bytes);
    return Array.from(bytes, function (v) { return v.toString(16).padStart(2, "0"); }).join("");
  }
  function groups(code, zone) {
    return (W.state.data.measurement_sets || []).filter(function (g) {
      return g.code === code && g.zone === zone;
    }).slice().sort(function (a, b) { return a.id.localeCompare(b.id); });
  }
  function sources(zone, excluded) {
    return (W.state.data.zones || []).reduce(function (all, z) {
      return all.concat((z.recorded || []).filter(function (r) {
        return (r.zone || z.code) === zone && r.level === "D0" &&
          typeof r.reading_c === "number" && Number.isFinite(r.reading_c) &&
          typeof r.revision === "string" && r.n !== excluded;
      }));
    }, []).sort(function (a, b) { return a.n - b.n; });
  }
  function slot(form, code, zone) {
    var key = code + ":" + zone;
    form.measurementUI = form.measurementUI || {};
    if (!form.measurementUI[key]) {
      var localKey = form.run_key + "_measurement_" + key;
      var saved = W.local && W.local.get(localKey);
      form.measurementUI[key] = saved && saved.run_id === form.run_id ? saved :
        {run_id:form.run_id, selected:"", draft:null, dirty:false};
      form.measurementUI[key].localKey = localKey;
      form.measurementUI[key].busy = false;
    }
    return form.measurementUI[key];
  }
  function persist(s) {
    if (W.local) W.local.set(s.localKey, {run_id:s.run_id, selected:s.selected,
      draft:s.draft, dirty:s.dirty, expanded:s.expanded});
  }
  function context(form, code, zone) {
    var s = slot(form, code, zone);
    var list = groups(code, zone);
    var selected = list.find(function (g) { return g.id === s.selected; });
    var inventory = sources(zone).map(function (r) { return {n:r.n, revision:r.revision}; });
    var blocked = "";
    if (s.selected && (!selected || list.some(function (g) {
      return g.stale || g.products.some(function (p) {return p.sources.some(function (ref) {
        return !inventory.some(function (r) {return r.n === ref.n && r.revision === ref.revision;});
      });});
    }))) blocked = "walk.measurement.stale";
    if (s.selected && s.dirty && s.draft) blocked = "walk.measurement.unsaved";
    return {selected:selected || null, enabled:!!s.selected, blocked:blocked,
      key:JSON.stringify({selected:s.selected, groups:list, inventory:inventory,
        unsaved:s.selected && s.dirty && s.draft})};
  }
  function product() { return {id:id(), label:"", facts:"", confirmed_product:false, sources:[]}; }
  function editable(g) {
    return {schema:1, id:g.id, revision:g.revision, code:g.code, zone:g.zone,
      line_label:g.line_label, confirmed:g.confirmed, products:copy(g.products)};
  }
  function validate(draft, available) {
    if (!draft || !draft.line_label.trim() || !draft.confirmed || !draft.products.length || draft.products.length > 30) return "walk.measurement.confirm";
    var seen = [];
    for (var i = 0; i < draft.products.length; i++) {
      var p = draft.products[i];
      if (!p.label.trim() || !p.confirmed_product || !p.sources.length) return "walk.measurement.confirm";
      for (var j = 0; j < p.sources.length; j++) {
        var ref = p.sources[j];
        if (seen.indexOf(ref.n) !== -1) return "walk.measurement.duplicate";
        seen.push(ref.n);
        if (!available.some(function (r) { return r.n === ref.n && r.revision === ref.revision; })) return "walk.measurement.stale";
      }
    }
    return seen.length > 60 ? "walk.measurement.limit" : "";
  }
  function panel(options) {
    var form = options.form, code = options.code, zone = options.zone;
    var s = slot(form, code, zone), list = groups(code, zone);
    var available = sources(zone, form.n);
    var box = W.el("details", "walk-measurements walk-form__section");
    box.setAttribute("data-measurement-manager", code);
    box.addEventListener("keydown", function (event) {
      // Product facts are multiline input; Enter must never submit the finding.
      if (event.target.tagName === "TEXTAREA") event.stopPropagation();
    });
    box.open = !!(s.expanded || s.selected || s.draft);
    box.addEventListener("toggle", function () { s.expanded = box.open; persist(s); });
    box.appendChild(W.el("summary", "", W.tx("walk.measurement.title")));
    box.appendChild(W.el("p", "walk-form__hint", W.tx("walk.measurement.explain")));
    function notify(render) {
      var confirmation = box.querySelector("[data-measurement-confirm-set]");
      if (confirmation && s.draft) confirmation.checked = !!s.draft.confirmed;
      persist(s); options.changed(!!render);
    }
    function button(key, fn) { return W.button("walk-link", W.tx(key), fn); }
    function input(labelKey, value, onInput, max, multiline) {
      var label = W.el("label", "walk-measurements__field", W.tx(labelKey));
      var field = W.el(multiline ? "textarea" : "input", multiline ? "walk-area" : "walk-input");
      if (!multiline) field.type = "text";
      field.value = value; field.maxLength = max;
      field.setAttribute("aria-label", W.tx(labelKey));
      field.addEventListener("input", function () { onInput(field.value); s.dirty = true; s.draft.confirmed = false; notify(false); });
      label.appendChild(field); return label;
    }
    function check(key, checked, fn) {
      var label = W.el("label", "walk-check");
      var field = W.el("input");field.type = "checkbox";field.checked = checked;
      if (key === "walk.measurement.confirm_set") field.setAttribute("data-measurement-confirm-set", "");
      field.addEventListener("change", function () { fn(field.checked);s.dirty = true;notify(false); });
      label.appendChild(field);label.appendChild(W.el("span", "", W.tx(key)));return label;
    }
    var selectLabel = W.el("label", "walk-measurements__field", W.tx("walk.measurement.select"));
    var select = W.el("select", "walk-input");select.setAttribute("aria-label", W.tx("walk.measurement.select"));
    var none = W.el("option", "", W.tx("walk.measurement.none"));none.value = "";select.appendChild(none);
    list.forEach(function (g) {
      var option = W.el("option", "", g.line_label + (g.stale ? " — " + W.tx("walk.measurement.stale_short") : ""));
      option.value = g.id;select.appendChild(option);
    });
    if (s.selected && !list.some(function (g) {return g.id === s.selected;})) {
      var missing = W.el("option", "", W.tx("walk.measurement.stale_short"));
      missing.value = s.selected; missing.disabled = true; select.appendChild(missing);
    }
    select.value = s.selected;
    select.disabled = s.busy;
    select.addEventListener("change", function () { s.selected = select.value;notify(true); });
    selectLabel.appendChild(select);box.appendChild(selectLabel);
    if (s.selected && context(form, code, zone).blocked) box.appendChild(W.el("p", "walk-form__error", W.tx(context(form, code, zone).blocked)));
    list.forEach(function (g) {
      var line = W.el("div", "walk-measurements__line");
      line.appendChild(W.el("strong", "", g.line_label));
      g.products.forEach(function (p) {
        line.appendChild(W.el("p", "", p.label + (p.facts ? " — " + p.facts : "")));
        p.sources.forEach(function (ref) {
          var record = available.find(function (r) { return r.n === ref.n && r.revision === ref.revision; });
          line.appendChild(W.el("p", "walk-form__hint", record ? sourceText(record) : W.tx("walk.measurement.source_stale", {n:ref.n})));
        });
      });
      var edit = button("walk.measurement.edit", function () { s.draft = editable(g);s.dirty = false;s.error = "";notify(true); });
      edit.disabled = s.busy;line.appendChild(edit);box.appendChild(line);
    });
    var create = button("walk.measurement.create", function () {
      s.draft = {schema:1,id:id(),revision:null,code:code,zone:zone,line_label:"",confirmed:false,products:[product()]};
      s.dirty = true;s.error = "";notify(true);
    });
    create.disabled = s.busy || list.length >= 20;box.appendChild(create);
    if (!available.length) box.appendChild(W.el("p", "walk-form__hint", W.tx("walk.measurement.no_sources")));
    if (s.draft) {
      var draft = s.draft;
      var editor = W.el("fieldset", "walk-measurements__editor");editor.disabled = !!s.busy;
      editor.appendChild(input("walk.measurement.line", draft.line_label, function (v) {draft.line_label = v;}, 120));
      draft.products.forEach(function (p, index) {
        var row = W.el("fieldset", "walk-measurements__product");
        row.appendChild(W.el("legend", "", W.tx("walk.measurement.product_number", {n:index + 1})));
        row.appendChild(input("walk.measurement.product", p.label, function (v) {p.label = v;}, 120));
        row.appendChild(input("walk.measurement.facts", p.facts, function (v) {p.facts = v;}, 500, true));
        row.appendChild(check("walk.measurement.confirm_product", p.confirmed_product, function (v) {p.confirmed_product = v;draft.confirmed = false;}));
        var choices = available.slice();
        p.sources.forEach(function (ref) {
          if (!choices.some(function (r) {return r.n === ref.n;})) choices.push({n:ref.n,revision:ref.revision,missing:true});
        });
        choices.forEach(function (record) {
          var label = W.el("label", "walk-check walk-measurements__source");
          var field = W.el("input");field.type = "checkbox";
          field.checked = p.sources.some(function (ref) {return ref.n === record.n;});
          var usedElsewhere = draft.products.some(function (other) {return other !== p && other.sources.some(function (ref) {return ref.n === record.n;});}) ||
            list.some(function (g) {return g.id !== draft.id && g.products.some(function (other) {return other.sources.some(function (ref) {return ref.n === record.n;});});});
          field.disabled = usedElsewhere || (record.missing && !field.checked);
          field.setAttribute("data-measurement-source", record.n);
          field.addEventListener("change", function () {
            p.sources = p.sources.filter(function (ref) {return ref.n !== record.n;});
            if (field.checked) p.sources.push({n:record.n,revision:record.revision});
            draft.confirmed = false;s.dirty = true;notify(true);
          });
          var outdated = record.missing || p.sources.some(function (ref) {return ref.n === record.n && ref.revision !== record.revision;});
          label.appendChild(field);label.appendChild(W.el("span", "", outdated ? W.tx("walk.measurement.source_stale", {n:record.n}) : sourceText(record)));
          (record.photos || []).forEach(function (photo) {if (W.photo && W.photo.thumb) label.appendChild(W.photo.thumb(photo));});
          row.appendChild(label);
        });
        row.appendChild(button("walk.measurement.remove_product", function () {draft.products.splice(index, 1);draft.confirmed = false;s.dirty = true;notify(true);}));
        editor.appendChild(row);
      });
      var add = button("walk.measurement.add_product", function () {draft.products.push(product());draft.confirmed = false;s.dirty = true;notify(true);});
      add.disabled = draft.products.length >= 30;editor.appendChild(add);
      editor.appendChild(check("walk.measurement.confirm_set", draft.confirmed, function (v) {draft.confirmed = v;}));
      editor.appendChild(button("walk.measurement.save", function () {write(false);}));
      if (draft.revision) editor.appendChild(button("walk.measurement.delete", function () {write(true);}));
      editor.appendChild(button("walk.measurement.cancel", function () {s.draft = null;s.dirty = false;s.error = "";notify(true);}));
      editor.appendChild(button("walk.measurement.rebind", function () {
        var current = groups(code, zone).find(function (g) {return g.id === draft.id;});
        if (current) draft.revision = current.revision;
        draft.products.forEach(function (p) {p.sources.forEach(function (ref) {
          var record = available.find(function (r) {return r.n === ref.n;});
          if (record) ref.revision = record.revision;
        });});
        draft.confirmed = false;s.dirty = true;s.error = "";notify(true);
      }));
      box.appendChild(editor);
    }
    var refresh = button("walk.measurement.refresh", function () {
      if (s.busy) return;
      s.busy = true;s.error = "";notify(true);
      W.post(W.urls.data, {}).then(function (res) {
        if (!options.current() || W.state.data.run_id !== form.run_id) return;
        if (!res.ok || !res.body || res.body.run_id !== form.run_id) throw new Error((res.body && res.body.message) || W.tx("walk.err.run_changed"));
        W.apply(res.body, true);
      }).catch(function (e) {s.error = e.message || W.tx("walk.err.network");}).finally(function () {s.busy = false;if (options.current()) notify(true);});
    });refresh.disabled = s.busy;box.appendChild(refresh);
    if (s.error) box.appendChild(W.el("p", "walk-form__error", s.error));
    return box;
    function write(remove) {
      if (s.busy) return;
      var error = remove ? "" : validate(s.draft, sources(zone, form.n));
      if (error) {s.error = W.tx(error);notify(true);return;}
      var value = remove ? {id:s.draft.id,revision:s.draft.revision} : copy(s.draft);
      var body = {op:"measurement_set",run_id:form.run_id,measurement_set:value};
      if (remove) body.delete = true;
      s.busy = true;s.error = "";notify(true);
      W.post(W.urls.finding, body, null, null, form.run_id).then(function (res) {
        if (!options.current() || W.state.data.run_id !== form.run_id) return;
        if (!res.ok || !res.body || res.body.run_id !== form.run_id) throw new Error((res.body && res.body.message) || W.tx("walk.err.run_changed"));
        W.apply(res.body, true);
        if (remove) {if (s.selected === value.id) s.selected = "";s.draft = null;}
        else {
          var saved = groups(code, zone).find(function (g) {return g.id === value.id;});
          if (!saved) throw new Error(W.tx("walk.measurement.unconfirmed"));
          s.selected = saved.id;s.draft = null;
        }
        s.dirty = false;
      }).catch(function (e) {s.error = e.message || W.tx("walk.err.network");}).finally(function () {s.busy = false;if (options.current()) notify(true);});
    }
  }
  function sourceText(record) {
    return W.tx("walk.measurement.source", {n:record.n, reading:record.reading_c}) + " — " + (record.text || record.words || "");
  }
  W.measurementSets = {context:context,panel:panel,sources:sources,groups:groups,slot:slot,validate:validate};
})();
