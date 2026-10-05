import {chromium} from '/Users/ac/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const out=fileURLToPath(new URL('./',import.meta.url));
const meta=JSON.parse(await fs.readFile(process.argv[3]||'/private/tmp/spd-human-review-20261005-preview.json','utf8'));
const attempt=process.argv[2]||'first';
const base='http://127.0.0.1:4183';
const browser=await chromium.launch({headless:true,executablePath:'/Users/ac/Library/Caches/ms-playwright/chromium-1161/chrome-mac/Chromium.app/Contents/MacOS/Chromium'});
const checks=[],errors=[];let page;
async function settle(){await page.evaluate(async()=>{await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));await Promise.allSettled(document.getAnimations().filter(a=>Number.isFinite(a.effect.getComputedTiming().endTime)).map(a=>a.finished));});}
try{
 const ctx=await browser.newContext({viewport:{width:1360,height:960}});
 let csrf=(await (await ctx.request.get(base+'/api/v1/csrf')).json()).token;
 let login=await ctx.request.post(base+'/api/v1/sessions',{headers:{Origin:base,'X-CSRF-Token':csrf},data:{email:'human-review@example.test',password:'local-test-password'}});assert.equal(login.status(),200);
 page=await ctx.newPage();page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/v1/projects/*/runs',r=>r.request().method()==='POST'?r.abort():r.continue());
 await page.goto(base,{waitUntil:'networkidle'});
 const skip=page.getByRole('button',{name:'跳过',exact:true});if(await skip.isVisible())await skip.click();
 async function open(run){await page.getByRole('button',{name:run.question,exact:true}).first().click();await page.getByLabel('人工复核',{exact:true}).waitFor();await page.getByRole('button',{name:'保存人工复核',exact:true}).waitFor();await settle();}
 async function close(){await page.keyboard.press('Escape');await settle();}
 async function status(text){const review=page.getByLabel('人工复核',{exact:true});await review.getByLabel('复核结论状态').click();await page.getByText(text,{exact:true}).last().click();}
 async function save(conclusion,basis,next=''){
  const review=page.getByLabel('人工复核',{exact:true});await review.getByLabel('人工结论',{exact:true}).fill(conclusion);await review.getByLabel('人工核查依据',{exact:true}).fill(basis);await review.getByLabel('复核下一步',{exact:true}).fill(next);
  const response=page.waitForResponse(r=>r.url().endsWith('/human-review')&&r.request().method()==='POST');await review.getByRole('button',{name:'保存人工复核',exact:true}).click();const r=await response;assert.equal(r.status(),200,await r.text());
  await page.getByLabel('人工复核',{exact:true}).getByRole('button',{name:'保存人工复核',exact:true}).waitFor();await settle();return r.json();
 }
 await open(meta.draft);
 assert.ok((await page.getByLabel('人工复核',{exact:true}).innerText()).includes('待人工复核'));
 assert.equal(await page.getByRole('button',{name:'确认并创建本人待办',exact:true}).isDisabled(),true);
 checks.push('draft confirmation blocked while current and ancestor review pending');
 await close();await open(meta.failed);
 const review=page.getByLabel('人工复核',{exact:true});assert.ok((await review.innerText()).includes('记录人工核查结论'));
 await review.getByText('人工核对库存、批次与消耗',{exact:true}).click();
 await review.getByRole('button',{name:/查看批次与消耗/}).first().click();await page.getByRole('tab',{name:'14日消耗',exact:true}).click();await settle();
 await page.screenshot({path:out+'manual-consumption.png'});checks.push('failed run exposes bound batch and consumption details without model calls');
 await close();await review.getByRole('button',{name:'保存人工复核',exact:true}).click();await page.getByText('请填写人工核查结论',{exact:true}).waitFor();
 checks.push('manual conclusion and basis required');
 await status('资料不足');const failed=await save('原始消耗记录仍需核实，暂不采纳处置建议。','已查看绑定库存和14日消耗记录。','核对原始台账后重新核查。');assert.equal(failed.status,'insufficient');assert.equal(failed.manual_only,true);
 assert.equal((await (await ctx.request.get(base+'/api/v1/runs/'+meta.failed.run_id)).json()).status,'failed');
 await page.getByText('人工复核历史 · 1 条',{exact:true}).click();await page.getByText('本人自查',{exact:true}).waitFor();await settle();await page.screenshot({path:out+'manual-failure-desktop.png'});
 checks.push('manual record persists with self review label while AI stays failed');
 await close();await open(meta.main);await status('人工确认');const main=await save('已逐项核对关注项，继续记录内部待办。','依据绑定快照和保存来源，核对业务时点及相关记录。');assert.equal(main.status,'confirmed');
 await close();await open(meta.draft);assert.equal(await page.getByRole('button',{name:'确认并创建本人待办',exact:true}).isDisabled(),true);
 await status('人工确认');await save('已人工核对待办草稿的核查范围和步骤。','已查看本次工具依据和原核查结论，明确待办仅记录核查工作。');
 assert.equal(await page.getByRole('button',{name:'确认并创建本人待办',exact:true}).isDisabled(),false);
 checks.push('both ancestor and draft review must pass before confirmation enabled');
 await page.getByLabel('任务标题',{exact:true}).fill('浏览器人工复核后待办');await page.getByLabel('处理步骤（每行一条，最多8条）',{exact:true}).fill('核对原始台账\n记录未解决信息');
 await page.getByPlaceholder('选择截止日期',{exact:true}).fill('2026-10-10');
 const confirmed=page.waitForResponse(r=>r.url().endsWith('/confirm')&&r.request().method()==='POST');await page.getByPlaceholder('选择截止日期',{exact:true}).press('Enter');assert.equal((await confirmed).status(),200);
 await page.getByText('已创建本人待办',{exact:true}).waitFor();checks.push('manual review then edited draft creates one internal task');
 await close();await open(meta.main);const feedback=page.getByLabel('核查反馈',{exact:true});await feedback.getByText('需要修正',{exact:true}).click();await feedback.getByLabel('反馈说明').fill('交期仍未核实，需要补查。');
 const feedbackResponse=page.waitForResponse(r=>r.url().endsWith('/feedback')&&r.request().method()==='POST');await feedback.getByRole('button',{name:'提交反馈',exact:true}).click();assert.equal((await feedbackResponse).status(),200);
 await page.getByLabel('人工复核',{exact:true}).getByText('发现错误 / 有争议',{exact:true}).first().waitFor();
 await status('发现错误 / 有争议');await page.getByLabel('人工结论',{exact:true}).fill('交期未核实，原建议暂不采纳。');await page.getByLabel('人工核查依据',{exact:true}).fill('根据纠错反馈核对现有订单信息。');await page.getByLabel('复核下一步',{exact:true}).fill('补查交期后重新评估。');
 await page.getByRole('button',{name:'保存人工复核',exact:true}).click();await page.getByText('请在结论中回应并勾选全部纠错反馈',{exact:true}).waitFor();
 checks.push('new correction feedback reopens dispute and requires explicit acknowledgement');
 await page.getByRole('checkbox',{name:/交期仍未核实/}).check();const errorRecord=await save('交期未核实，原建议暂不采纳。','已回应纠错反馈并核对订单信息。','补查交期后重新评估。');assert.equal(errorRecord.status,'error');assert.equal(errorRecord.pending_feedback.length,0);
 await page.getByText('人工复核历史 · 2 条',{exact:true}).click();await settle();await page.screenshot({path:out+'review-dispute-desktop.png'});
 assert.equal((await (await ctx.request.get(base+'/api/v1/projects/'+meta.project_id+'/tasks')).json()).length,1);
 await page.reload({waitUntil:'networkidle'});await open(meta.main);assert.ok((await page.getByLabel('人工复核',{exact:true}).innerText()).includes('发现错误 / 有争议'));
 await page.getByText('人工复核历史 · 2 条',{exact:true}).click();assert.ok((await page.getByLabel('人工复核',{exact:true}).innerText()).includes('已逐项核对关注项'));
 checks.push('refresh preserves original review and later dispute; existing task retained');
 await page.setViewportSize({width:390,height:844});await settle();const dimensions=await page.evaluate(()=>({client:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth}));assert.equal(dimensions.client,dimensions.scroll);
 const box=await page.getByLabel('人工复核',{exact:true}).boundingBox();assert.ok(box.x>=0&&box.x+box.width<=390,JSON.stringify(box));await page.screenshot({path:out+'review-mobile.png',fullPage:true});
 checks.push('390px review form and history stay within viewport');
 await page.setViewportSize({width:1360,height:960});await close();await open(meta.ordinary);assert.ok((await page.getByLabel('人工复核',{exact:true}).innerText()).includes('可人工抽查'));
 checks.push('ordinary results remain pending and available for human sampling');
 await close();await page.getByLabel('筛选人工复核').click();await page.getByText('发现错误 / 有争议',{exact:true}).last().click();assert.equal(await page.getByRole('button',{name:meta.main.question,exact:true}).count(),1);assert.equal(await page.getByRole('button',{name:meta.ordinary.question,exact:true}).count(),0);
 checks.push('review status filter isolates disputed runs');
 csrf=(await (await ctx.request.get(base+'/api/v1/csrf')).json()).token;
 login=await ctx.request.post(base+'/api/v1/sessions',{headers:{Origin:base,'X-CSRF-Token':csrf},data:{email:'human-reviewer@example.test',password:'local-test-password'}});assert.equal(login.status(),200);
 const rurl=base+'/api/v1/runs/'+meta.main.run_id+'/human-review';const current=await (await ctx.request.get(rurl)).json();
 const other=await ctx.request.post(rurl,{headers:{Origin:base,'X-CSRF-Token':csrf,'Idempotency-Key':'browser-other-reviewer'},data:{revision:current.revision,source_token:current.source_token,status:'confirmed',conclusion:'其他账号已复核交期相关争议。',basis:'受控浏览器验收：补查记录并回应争议，非业务签收。',next_step:'',evidence_ids:[],handled_feedback_ids:[]}});
 assert.equal(other.status(),200);assert.equal((await other.json()).items[0].self_review,false);
 checks.push('server attributes other account review separately from self review');
 assert.deepEqual(errors,[]);await fs.writeFile(out+'browser-results.json',JSON.stringify({kind:'isolated_browser_controlled_provider',real_model_calls:0,cloud_uploads:0,checks,errors,dimensions},null,2)+'\n');console.log(JSON.stringify({checks,errors,dimensions}));
}catch(e){if(page){await page.screenshot({path:out+`browser-${attempt}-failure.png`,fullPage:true});await fs.writeFile(out+`browser-${attempt}-page.txt`,await page.locator('body').innerText());}await fs.writeFile(out+`browser-${attempt}-failure.json`,JSON.stringify({checks,errors,error:String(e)},null,2)+'\n');throw e;}finally{await browser.close();}
