"""Native miniapp finish in a static browser; HTTP and delivery are synthetic."""

from __future__ import annotations

from test_web_walk_ux_browser import STATIC, page  # noqa: F401

from src.web.texts_walk import WALK_TEXTS


def native(page):  # noqa: F811
    texts = {key: value["ru"] for key, value in WALK_TEXTS.items()}
    page.evaluate(
        """texts => {
          const W=DecimusWalk; window.ops=[]; window.store={}; window.chatFallback=0;
          W.local={get:key=>store[key]||null,set:(key,value)=>store[key]=JSON.parse(JSON.stringify(value)),
            drop:key=>delete store[key]};
          W.state.data={key:'walk_fixture',run_id:'run-fixture',unit:'Synthetic unit',
            date:'2026-10-31',state:'active',lang:'ru',texts,
            info:[{code:'INF01',kind:'text',q:'Synthetic strengths',value:''},
              {code:'INF06',kind:'text',q:'Synthetic growth',value:''}],
            zones:[{code:'dining',title:'Area',recorded:[{n:1,code:'TEST01',level:'D1',
              text:'Synthetic finding',comment:'Synthetic recommendation',photos:[]}]}]};
          W.tx=(key,args)=>{let text=W.state.data.texts[key]||key;
            Object.entries(args||{}).forEach(([key,value])=>text=text.replace('{'+key+'}',value));
            return text;};
          W.apply=data=>W.state.data=data; W.urls.app='/app'; W.urls.info='/info';
          W.finish={ask:()=>chatFallback++};
          W.sheet={open:()=>{},isOpen:()=>false};
          window.submitted=false; window.failInfo=false; window.finished=false;
          window.review=()=>({run_id:'run-fixture',revision:'revision-fixture',
            summary:{pct:98.5,grade:'A',label:'Synthetic score',total:1,counts:{D1:1}},
            report_langs:[{code:'ru',label:'Русский'}],data:W.state.data});
          W.post=(url,body)=>{ops.push({url,body});
            if(url==='/info'){
              if(failInfo){failInfo=false;
                return Promise.resolve({ok:false,body:{message:'Synthetic network error'}});}
              W.state.data.info.find(field=>field.code===body.code).value=body.value;
              return Promise.resolve({ok:true,body:W.state.data});
            }
            if(body.op==='finish_review')return Promise.resolve({ok:true,body:review()});
            if(body.op==='finish_submit'){submitted=true;
              return Promise.resolve({ok:true,body:{status:'started'}});}
            return Promise.resolve({ok:true,body:finished?{status:'completed',data:W.state.data}:
              {status:submitted?'started':'ready'}});
          };
          const timeout=window.setTimeout;
          window.setTimeout=(fn,ms)=>ms===1500?(window.pollFinish=fn,999):timeout(fn,ms);
        }""",
        texts,
    )
    page.add_script_tag(path=str(STATIC / "walk-finish-native.js"))
    page.evaluate("DecimusWalk.finish.ask()")
    page.wait_for_selector("#finish-field-INF01")


def test_native_finish_keeps_input_after_error_and_requires_explicit_confirmation(page):  # noqa: F811
    native(page)
    page.evaluate("failInfo=true")
    page.locator("#finish-field-INF01").fill("Synthetic strengths answer")
    page.get_by_role("button", name="Проверить итог", exact=True).click()
    page.wait_for_function(
        "document.querySelector('.walk-finish__error').textContent==='Synthetic network error'"
    )
    assert page.locator("#finish-field-INF01").input_value() == "Synthetic strengths answer"
    assert (
        page.evaluate("store['walk_fixture_finish_run-fixture'].fields.INF01")
        == "Synthetic strengths answer"
    )
    page.get_by_role("button", name="Проверить итог", exact=True).click()
    page.wait_for_selector("#finish-consent")
    assert "98.5% · A" in page.locator(".walk-finish__score").inner_text()
    assert "Synthetic finding" in page.locator(".walk-finish__record").inner_text()
    assert "Synthetic recommendation" in page.locator(".walk-finish__record").inner_text()
    assert page.evaluate("ops.filter(x=>x.body.op==='finish_submit').length") == 0
    page.get_by_role("button", name="Подтвердить и сформировать отчёт", exact=True).click()
    assert page.evaluate("ops.filter(x=>x.body.op==='finish_submit').length") == 0
    page.locator("#finish-consent").check()
    page.locator("#finish-skip").check()
    page.get_by_role("button", name="Подтвердить и сформировать отчёт", exact=True).click()
    page.wait_for_function("submitted")
    requests = page.evaluate("ops.filter(x=>x.body.op==='finish_submit')")
    assert len(requests) == 1
    assert requests[0]["body"]["confirmed"] and requests[0]["body"]["skip_missing_info"]
    assert requests[0]["body"]["run_id"] == "run-fixture"
    page.evaluate("finished=true;pollFinish()")
    page.wait_for_function(
        "document.querySelector('.walk-finish__body').textContent.includes('Проверка завершена')"
    )
    assert page.evaluate("chatFallback") == 0
    assert page.evaluate("store['walk_fixture_finish_run-fixture']||null") is None


def test_native_cancel_and_reopen_recovers_per_run_input_without_chat(page):  # noqa: F811
    native(page)
    page.locator("#finish-field-INF06").fill("Synthetic unsaved growth")
    page.keyboard.press("Escape")
    assert page.locator(".walk-finish").count() == 0
    page.evaluate("DecimusWalk.finish.ask()")
    page.wait_for_selector("#finish-field-INF06")
    assert page.locator("#finish-field-INF06").input_value() == "Synthetic unsaved growth"
    assert page.evaluate("ops.filter(x=>x.url==='/info').length") == 0
    assert page.evaluate("chatFallback") == 0


def test_native_chat_remains_an_explicit_fallback(page):  # noqa: F811
    native(page)
    page.get_by_role("button", name="Продолжить в чате", exact=True).click()
    assert page.evaluate("chatFallback") == 1
    assert page.locator(".walk-finish").count() == 0
