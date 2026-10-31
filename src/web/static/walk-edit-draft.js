/* Existing-record drafts stay tied to the authoritative run, record and revision. */
(function () {
  "use strict";
  var W = window.DecimusWalk;
  var fields = ["mode", "zone", "code", "level", "text", "comment", "repeat", "reading", "readingSource", "readingConfirmed"];
  function id() {
    var bytes = new Uint8Array(16); window.crypto.getRandomValues(bytes);
    return Array.from(bytes).map(function (n) { return n.toString(16).padStart(2, "0"); }).join("");
  }
  function index(form) { return form.editIndexKey; }
  function rememberKey(form) {
    var keys = W.local.get(index(form));
    if (!Array.isArray(keys)) keys = [];
    if (keys.indexOf(form.draftKey) === -1) keys.push(form.draftKey);
    W.local.set(index(form), keys);
  }
  function valid(draft, form) {
    return draft && draft.run_id === form.run_id && draft.n === form.n && draft.values && typeof draft.values === "object";
  }
  function apply(form, draft) {
    fields.forEach(function (key) { if (Object.prototype.hasOwnProperty.call(draft.values, key)) form[key] = draft.values[key]; });
    form.commentOpen = !!form.comment;
    var refs = form.source_record.photos.map(function (p) {return p.ref;});
    form.removed = (draft.removed || []).filter(function (ref) {return refs.indexOf(ref) !== -1;});
    form.photos = form.photos.filter(function (p) {return form.removed.indexOf(p.ref) === -1;});
    form.restored = true;
  }
  function completed(draft, form) {
    if(!draft.request_id)return null;
    return (W.state.data.finding_history || []).filter(function (event) {
      if(event.kind !== "edit" || event.run_id !== form.run_id || event.request_id !== draft.request_id || !event.after || event.after.length!==1)return false;
      var saved=event.after[0],v=draft.values;
      var reading=v.reading === null || v.reading === undefined || String(v.reading).trim()==="" ? null : Number(String(v.reading).trim().replace(",",".").replace(/\s*°\s*[CcСс]?$/,""));
      return saved.n===form.n && saved.code===v.code && saved.level===v.level && saved.zone===v.zone && saved.text===(v.text || "").trim() && (saved.comment || "")===(v.comment || "").trim() && !!saved.repeat===!!v.repeat && (saved.reading_c == null ? null : saved.reading_c)===reading &&
        (draft.photos || []).every(function (ref) {return saved.photos.indexOf(ref)!==-1;}) &&
        (draft.pending || []).every(function (p) {return p.ref && saved.photos.indexOf(p.ref)!==-1;}) &&
        (draft.removed || []).every(function (ref) {return saved.photos.indexOf(ref)===-1;});
    })[0] || null;
  }
  function init(form, record) {
    if (!record || !/^[a-f0-9]{64}$/.test(record.revision || "")) return;
    form.editIndexKey = W.state.data.key + "_edit_index_" + form.n;
    form.draftKey = W.state.data.key + "_edit_" + form.n + "_" + record.revision;
    form.editRevision = record.revision;
    var draft = W.local.get(form.draftKey);
    if (valid(draft, form) && draft.source_revision === record.revision) {
      apply(form, draft);
      form.editRequestId = draft.request_id;
      form.editSignature = draft.request_signature;
      form.editRecoveryKeys = draft.recovery_keys || [];
    }
    var keys = W.local.get(index(form));
    form.editCompleted=[];
    form.editRecovery = (Array.isArray(keys) ? keys : []).filter(function (key) {return key !== form.draftKey;}).map(function (key) {
      return {key:key, draft:W.local.get(key)};
    }).filter(function (entry) {
      if(!valid(entry.draft,form))return false;
      var event=completed(entry.draft,form);
      if(event){entry.accepted=event.after[0].photos;form.editCompleted.push(entry);return false;}
      return true;
    });
  }
  function save(form) {
    if (!form.editRevision) return;
    var values = {};
    fields.forEach(function (key) {if (form[key] !== undefined) values[key] = form[key];});
    var old = W.local.get(form.draftKey) || {};
    W.local.set(form.draftKey, Object.assign({}, old, {
      run_id:form.run_id, n:form.n, source_revision:form.editRevision, values:values,
      removed:form.removed.slice(), photos:form.photos.filter(function (p) {return p.fresh && p.ref;}).map(function (p) {return p.ref;}),
      pending:form.photos.filter(function (p) {return p.fresh;}).map(function (p) {return {id:p.entryId || null, ref:p.ref || null, receiptIds:p.receiptIds || []};}),
      request_id:form.editRequestId || null, request_signature:form.editSignature || null, recovery_keys:form.editRecoveryKeys || [],
    }));
    rememberKey(form);
  }
  function body(form, edit) {
    edit.source_revision = form.editRevision || form.source_record.revision;
    var signature = JSON.stringify(edit);
    if (form.editSignature !== signature || !form.editRequestId) form.editRequestId = id();
    form.editSignature = signature;
    edit.request_id = form.editRequestId;
    save(form);
    return edit;
  }
  function clear(form) { if (form.editRevision) W.local.drop(form.draftKey); }
  function release(form) {
    (form.editConsumers || []).forEach(function (stop) {stop();});form.editConsumers=[];
    (form.editPreviewUrls || []).forEach(function (url) {URL.revokeObjectURL(url);});form.editPreviewUrls=[];
  }
  function append(form, entry, ref) {
    if (entry.run_id !== form.run_id) return;
    var p=form.photos.filter(function (photo) {return photo.entryId === entry.id || (ref && photo.ref === ref);})[0];
    if (!p) {p={id:"edit-recovery-"+entry.id, fresh:true, own:true, draftKey:entry.key, run_id:entry.run_id, mode:entry.mode};form.photos.push(p);}
    p.editReceipts=p.editReceipts || [];
    if (!p.editReceipts.some(function (receipt) {return receipt.id === entry.id;})) p.editReceipts.push({id:entry.id,key:entry.key});
    p.receiptIds=p.receiptIds || [];
    if (p.receiptIds.indexOf(entry.id) === -1) p.receiptIds.push(entry.id);
    p.entryId=entry.id;p.ref=ref || null;p.state=ref ? "done" : entry.upload_error ? "failed" : "waiting";
    if (!p.url && entry.blob) {
      p.url=URL.createObjectURL(entry.blob);(form.editPreviewUrls || (form.editPreviewUrls=[])).push(p.url);
    }
  }
  function activate(form, refresh, isCurrent) {
    form.editRefresh=refresh;form.editIsCurrent=isCurrent;
    connect(form,form.draftKey);
    (form.editCompleted || []).forEach(function (entry) {
      if(!W.offline || !W.offline.list || !W.offline.ack)return;
      W.offline.list(entry.key).then(function (rows) {
        if(!isCurrent() || W.state.data.run_id !== form.run_id)return;
        return W.offline.ack(entry.key,form.run_id,rows.filter(function (row) {return row.run_id===form.run_id && entry.accepted.indexOf(row.uploaded_ref)!==-1;}).map(function (row) {return row.id;}));
      }).then(function () {return W.offline.list(entry.key);}).then(function (rows) {
        if(isCurrent() && !rows.length && JSON.stringify(W.local.get(entry.key))===JSON.stringify(entry.draft))W.local.drop(entry.key);
      },function () {if(isCurrent())W.toast(W.tx("walk.err.network"),"warn");});
    });
    (form.editRecoveryKeys || []).forEach(function (key) {connect(form,key);});
  }
  function connect(form, key) {
    if (!W.offline || !W.offline.register || !W.offline.list) return;
    var prefix=form.draftKey.slice(0,-64);
    if (key.slice(0,-64) !== prefix || !/^[a-f0-9]{64}$/.test(key.slice(-64))) return;
    form.editConnected=form.editConnected || [];
    if(form.editConnected.indexOf(key)!==-1)return;
    form.editConnected.push(key);
    var live=function () {return form.editIsCurrent && form.editIsCurrent() && W.state.data.run_id === form.run_id;};
    var update=function (entry,ref) {if(!live())return false;append(form,entry,ref);save(form);form.editRefresh();return true;};
    (form.editConsumers || (form.editConsumers=[])).push(W.offline.register(key,{uploaded:update,failed:function (entry) {if(!live())return false;var photo=form.photos.filter(function (p) {return p.entryId===entry.id;})[0];if(photo)photo.state="failed";form.editRefresh();return true;}}));
    W.offline.list(key).then(function (rows) {if(!live())return;rows.forEach(function (row) {append(form,row,row.uploaded_ref || null);});save(form);form.editRefresh();}, function () {if(live())W.toast(W.tx("walk.err.network"),"warn");});
  }
  function ack(form, refs) {
    var groups={};
    form.photos.forEach(function (photo) {
      if(refs.indexOf(photo.ref)===-1)return;
      (photo.editReceipts || []).forEach(function (receipt) {(groups[receipt.key] || (groups[receipt.key]=[])).push(receipt.id);});
    });
    if(!W.offline || !W.offline.ack)return Promise.resolve();
    return Promise.all(Object.keys(groups).map(function (key) {return W.offline.ack(key,form.run_id,groups[key]).then(function () {return W.offline.list(key);}).then(function (rows) {if(!rows.length && key !== form.draftKey)W.local.drop(key);});}));
  }
  function panel(form, refresh) {
    if (!form.editRecovery || !form.editRecovery.length) return null;
    var box = W.el("section", "walk-form__section");
    box.appendChild(W.el("h3", "", W.tx("walk.edit.recovery")));
    box.appendChild(W.el("p", "", W.tx("walk.edit.changed")));
    form.editRecovery.forEach(function (entry) {
      var d = entry.draft, v = d.values;
      var item = W.el("details", "walk-form__section");
      item.addEventListener("toggle", function () {
        if(!item.open || item.dataset.previewLoaded || !W.offline || !W.offline.list)return;
        item.dataset.previewLoaded="true";
        W.offline.list(entry.key).then(function (rows) {
          if(!item.isConnected || W.state.data.run_id !== form.run_id)return;
          rows.filter(function (row) {return row.run_id === form.run_id && row.blob;}).forEach(function (row) {
            var url=URL.createObjectURL(row.blob);(form.editPreviewUrls || (form.editPreviewUrls=[])).push(url);
            var img=W.el("img", "walk-thumb");img.src=url;img.alt=W.tx("walk.edit.recovery");item.appendChild(img);
          });
        }, function () {if(item.isConnected)W.toast(W.tx("walk.err.network"),"warn");});
      });
      item.appendChild(W.el("summary", "", (v.code || "")+" · "+(v.level || "")+" · "+(v.zone || "")));
      item.appendChild(W.el("p", "", v.text || ""));
      if (v.comment) item.appendChild(W.el("p", "", v.comment));
      if (v.reading !== null && v.reading !== undefined) item.appendChild(W.el("p", "", String(v.reading)+" °C"));
      item.appendChild(W.el("p", "", W.tx("walk.edit.removed", {n:(d.removed || []).length})));
      item.appendChild(W.el("p", "", W.tx("walk.edit.pending", {n:(d.pending || []).length})));
      if ((d.pending || []).length) item.appendChild(W.el("p", "", W.tx("walk.edit.photo_recovery")));
      item.appendChild(W.button("walk-btn", W.tx("walk.edit.restore"), function () {
        apply(form, d);
        form.editRecoveryKeys=form.editRecoveryKeys || [];
        if(form.editRecoveryKeys.indexOf(entry.key)===-1)form.editRecoveryKeys.push(entry.key);
        connect(form,entry.key);save(form);refresh();
      }));
      item.appendChild(W.button("walk-btn walk-btn--danger", W.tx("walk.edit.discard"), function () {
        var discard=function () {
          W.local.drop(entry.key); form.editRecovery = form.editRecovery.filter(function (x) {return x !== entry;});item.remove();
        };
        if(W.offline && W.offline.list && W.offline.remove) {
          W.offline.list(entry.key).then(function (rows) {
            return Promise.all(rows.filter(function (row) {return row.run_id === form.run_id;}).map(function (row) {return W.offline.remove(row.id);}));
          }).then(discard,function () {W.toast(W.tx("walk.err.network"),"warn");});
        } else if(!(d.pending || []).length) discard();
      }));
      box.appendChild(item);
    });
    return box;
  }
  W.editDraft = {init:init, save:save, body:body, clear:clear, panel:panel, activate:activate, ack:ack, release:release};
})();
