/* Human-confirmed split: explicit parts and photo allocation, one atomic server write. */
(function () {
  "use strict";
  var W = window.DecimusWalk;
  var el = W.el;
  var tx = W.tx;
  var current = null;
  var node = null;

  function blank() { return {code:"", level:"", zone:"", text:"", comment:"", repeat:false, reading_c:null, photos:[]}; }
  function requestId() {
    if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID().replace(/-/g, "");
    var bytes = new Uint8Array(16); window.crypto.getRandomValues(bytes);
    return Array.from(bytes).map(function (b) { return b.toString(16).padStart(2, "0"); }).join("");
  }
  function remember() {
    W.local.set(current.key, {run_id:current.run_id, revision:current.source.revision,
      request_id:current.request_id, parts:current.parts});
  }
  function field(box, key, control) {
    var label = el("label", "walk-form__label", tx("walk.split." + key));
    label.appendChild(control); box.appendChild(label);
  }
  function select(options, value, changed) {
    var input = el("select", "walk-input");
    var empty = el("option", "", tx("walk.split.choose")); empty.value=""; input.appendChild(empty);
    options.forEach(function (option) { var node=el("option", "", option.label);node.value=option.value;input.appendChild(node); });
    input.value=value;
    input.addEventListener("change", function () { changed(input.value); remember(); });
    return input;
  }
  function text(box, key, value, changed) {
    var area=el("textarea", "walk-input");area.value=value;area.rows=2;
    area.addEventListener("input", function () {changed(area.value);remember();});field(box,key,area);
  }
  function check(box, label, value, changed) {
    var row=el("label", "walk-check");var input=el("input");input.type="checkbox";input.checked=value;
    input.addEventListener("change",function () {changed(input.checked);remember();});
    row.appendChild(input);row.appendChild(el("span", "", label));box.appendChild(row);return input;
  }
  function photoNumbers(refs, source) {
    return refs.map(function (ref) {return tx("walk.split.photo", {n:source.photos.map(function (p) {return p.ref;}).indexOf(ref)+1});}).join(", ");
  }
  function shared() {
    var counts={};current.parts.forEach(function (part) {part.photos.forEach(function (ref) {counts[ref]=(counts[ref]||0)+1;});});
    return Object.keys(counts).filter(function (ref) {return counts[ref]>1;});
  }
  function valid() {
    var all=[];
    var good=current.parts.every(function (part) {
      all=all.concat(part.photos);
      return part.code && part.level && part.zone && part.text.trim() &&
        (!current.source.photos.length || part.level==="R" || part.photos.length);
    });
    return good && current.source.photos.every(function (p) {return all.indexOf(p.ref)!==-1;}) &&
      all.every(function (ref) {return current.source.photos.some(function (p) {return p.ref===ref;});});
  }
  function sourcePreview(body) {
    var source=current.source;
    body.appendChild(el("h3", "", tx("walk.split.source")));
    body.appendChild(el("p", "", source.code+" · "+source.level+" · "+source.zone));
    body.appendChild(el("p", "", source.text));
    if(source.comment)body.appendChild(el("p", "", source.comment));
    source.photos.forEach(function (photo,i) {var box=el("span", "walk-thumb");box.appendChild(W.photo.thumb(photo));box.appendChild(el("span", "", tx("walk.split.photo",{n:i+1})));body.appendChild(box);});
  }
  function renderPart(body, part, index) {
    var box=el("fieldset", "walk-form__section");box.appendChild(el("legend", "", tx("walk.split.part",{n:index+1})));
    var items=W.state.data.items;
    field(box,"item",select(items.map(function (item) {return {value:item.code,label:item.label+" · "+item.q};}),part.code,function (value) {
      part.code=value;part.level="";remember();render(false);
    }));
    var item=items.filter(function (item) {return item.code===part.code;})[0];
    var levels=item ? item.levels.slice() : [];
    if (item && levels.indexOf("R")===-1) levels.push("R");
    field(box,"level",select(levels.map(function (level) {return {value:level,label:level};}),part.level,function (value) {part.level=value;}));
    field(box,"zone",select(W.state.data.zones.map(function (zone) {return {value:zone.code,label:zone.title};}),part.zone,function (value) {part.zone=value;}));
    text(box,"text",part.text,function (value) {part.text=value;});
    text(box,"comment",part.comment,function (value) {part.comment=value;});
    check(box,tx("walk.split.repeat"),part.repeat,function (value) {part.repeat=value;});
    var reading=el("input", "walk-input");reading.type="number";reading.step="any";reading.value=part.reading_c===null ? "" : part.reading_c;
    reading.addEventListener("input",function () {part.reading_c=reading.value==="" ? null : Number(reading.value);remember();});field(box,"reading",reading);
    current.source.photos.forEach(function (photo,i) {
      check(box,tx("walk.split.photo",{n:i+1}),part.photos.indexOf(photo.ref)!==-1,function (on) {
        part.photos=part.photos.filter(function (ref) {return ref!==photo.ref;});if(on)part.photos.push(photo.ref);
      });
    });
    if(current.parts.length>2)box.appendChild(W.button("walk-link",tx("walk.split.remove"),function () {current.parts.splice(index,1);remember();render(false);}));
    body.appendChild(box);
  }
  function render(review) {
    if(!current)return;
    node.textContent="";
    var header=el("header", "walk-sheet__head");header.appendChild(W.button("walk-sheet__back", "‹ "+tx("walk.sheet.back"),close));
    header.appendChild(el("h2", "walk-sheet__title",tx("walk.split.title")));node.appendChild(header);
    var body=el("div", "walk-sheet__body");sourcePreview(body);
    if(current.error)body.appendChild(el("p", "walk-form__error",current.error));
    if(!review) {
      body.appendChild(el("p", "walk-form__note",tx("walk.split.hint")));
      current.parts.forEach(function (part,i) {renderPart(body,part,i);});
      var add=W.button("walk-btn",tx("walk.split.add"),function () {current.parts.push(blank());remember();render(false);});add.disabled=current.parts.length>=5;body.appendChild(add);
      body.appendChild(W.button("walk-btn walk-btn--primary",tx("walk.split.review"),function () {
        if(!valid()){current.error=tx("walk.split.invalid");render(false);return;}
        current.error=null;remember();render(true);
      }));
    } else {
      current.parts.forEach(function (part,i) {
        var card=el("section", "walk-form__section");card.appendChild(el("h3", "",tx("walk.split.part",{n:i+1})));
        card.appendChild(el("p", "",part.code+" · "+part.level+" · "+part.zone));
        card.appendChild(el("p", "",part.text));if(part.comment)card.appendChild(el("p", "",part.comment));
        card.appendChild(el("p", "",tx("walk.split.repeat")+": "+tx(part.repeat ? "walk.info.yes" : "walk.info.no")));
        card.appendChild(el("p", "",tx("walk.split.reading")+": "+(part.reading_c===null ? "—" : part.reading_c)));
        card.appendChild(el("p", "",photoNumbers(part.photos,current.source)));body.appendChild(card);
      });
      var duplicated=shared();var consent=null;
      if(duplicated.length){body.appendChild(el("p", "",photoNumbers(duplicated,current.source)));consent=check(body,tx("walk.split.shared"),false,function () {});}
      var confirmed=check(body,tx("walk.split.confirmed"),false,function () {});
      body.appendChild(W.button("walk-btn",tx("walk.split.edit"),function () {current.error=null;render(false);}));
      body.appendChild(W.button("walk-btn walk-btn--primary",tx("walk.split.confirm"),function () {
        if(!confirmed.checked || (consent && !consent.checked)){current.error=tx("walk.split.invalid");render(true);return;}
        submit(duplicated);
      }));
    }
    node.appendChild(body);
  }
  function submit(duplicated) {
    var state=current;remember();
    node.querySelectorAll("button,input").forEach(function (control) {control.disabled=true;});
    W.api.write(W.urls.finding,{op:"split",n:state.source.n,source_revision:state.source.revision,
      request_id:state.request_id,confirmed:true,shared_photos:duplicated,parts:state.parts},state.run_id).then(function (response) {
      if(!response.ok)throw new Error((response.body && response.body.message)||tx("walk.error"));
      W.local.drop(state.key);if(current!==state)return;
      close();if(W.state.data.run_id===state.run_id)W.apply(response.body);
      W.toast(tx("walk.split.saved"),"ok");
    }).catch(function (error) {if(current===state){state.error=error.message||tx("walk.err.network");render(true);}});
  }
  function close() {
    if(node)node.remove();node=null;current=null;
    document.documentElement.classList.remove("has-sheet");
    if(W.tg && W.supports("6.1")){W.tg.BackButton.offClick(close);W.app.syncBack();}
  }
  function open(source) {
    if(current)close();
    var data=W.state.data;var key=data.key+"_split_"+source.n;var draft=W.local.get(key);
    current={key:key,run_id:data.run_id,source:source,request_id:requestId(),parts:[blank(),blank()]};
    if(draft && draft.run_id===data.run_id && Array.isArray(draft.parts)){
      current.parts=draft.parts;
      if(draft.revision===source.revision)current.request_id=draft.request_id;
      else current.error=tx("walk.split.conflict");
    }
    node=el("div", "walk-sheet");node.setAttribute("role","dialog");node.setAttribute("aria-modal","true");
    document.body.appendChild(node);document.documentElement.classList.add("has-sheet");render(false);remember();
    if(W.tg && W.supports("6.1")){W.tg.BackButton.onClick(close);W.tg.BackButton.show();}
  }
  function historyPanel() {
    var history=W.state.data.finding_history || [];if(!history.length)return null;
    var panel=el("details", "walk-form__section");panel.appendChild(el("summary", "",tx(history.some(function (event) {return event.kind === "edit" || event.kind === "clarification";}) ? "walk.edit.history" : "walk.split.history")));
    history.forEach(function (event) {
      if(event.kind === "clarification") {
        var note=el("section", "walk-form__section");
        note.appendChild(el("h3", "",tx("walk.edit.clarification")+" #"+event.n+" · "+event.at));
        (event.clarifications || []).forEach(function (fact) {
          note.appendChild(el("p", "",tx("walk.edit.question")+": "+fact.question));
          note.appendChild(el("p", "",tx("walk.edit.answer")+": "+fact.answer));
        });panel.appendChild(note);return;
      }
      var source=event.before;var item=el("section", "walk-form__section");item.appendChild(el("h3", "",tx(event.kind === "edit" ? "walk.edit.before" : "walk.split.source")+" #"+source.n+" · "+event.at));
      item.appendChild(el("p", "",source.code+" · "+source.level+" · "+source.zone+" · "+source.text));
      if(event.kind === "edit")item.appendChild(el("p", "",tx("walk.edit.photo_refs",{n:source.photos.length})));
      if(source.repeat)item.appendChild(el("p", "",tx("walk.rec.repeat")));
      if(source.comment)item.appendChild(el("p", "",source.comment));
      if(source.reading_c !== null && source.reading_c !== undefined)item.appendChild(el("p", "",source.reading_c+" °C"));
      event.after.forEach(function (part) {item.appendChild(el("p", "",(event.kind === "edit" ? tx("walk.edit.after")+" · " : "")+"#"+part.n+" · "+part.code+" · "+part.level+" · "+part.zone+" · "+part.text+" · "+tx(event.kind === "edit" ? "walk.edit.photo_refs" : "walk.split.photo_count",{n:part.photos.length})));if(part.repeat)item.appendChild(el("p", "",tx("walk.rec.repeat")));if(part.comment)item.appendChild(el("p", "",part.comment));if(part.reading_c !== null && part.reading_c !== undefined)item.appendChild(el("p", "",part.reading_c+" °C"));});panel.appendChild(item);
    });return panel;
  }
  W.split={open:open,close:close,historyPanel:historyPanel,isOpen:function () {return !!current;}};
})();
