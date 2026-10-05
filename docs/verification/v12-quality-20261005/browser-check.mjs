import {chromium} from '/Users/ac/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const output=fileURLToPath(new URL('./',import.meta.url));
const attempt=process.argv[2]||'first';
const browser=await chromium.launch({headless:true,executablePath:'/Users/ac/Library/Caches/ms-playwright/chromium-1161/chrome-mac/Chromium.app/Contents/MacOS/Chromium'});
const checks=[],errors=[];let page;
async function settle() {
 await page.evaluate(async()=>{
  await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
  await Promise.allSettled(document.getAnimations().filter(a=>Number.isFinite(a.effect.getComputedTiming().endTime)).map(a=>a.finished));
 });
}
try {
 const context=await browser.newContext({viewport:{width:1280,height:900}});const base='http://127.0.0.1:4182';
 const csrf=(await (await context.request.get(base+'/api/v1/csrf')).json()).token;
 const login=await context.request.post(base+'/api/v1/sessions',{headers:{Origin:base,'X-CSRF-Token':csrf},data:{email:'v12-browser@example.test',password:'local-test-password'}});
 assert.equal(login.status(),200);const me=await login.json();
 const runs=await (await context.request.get(base+'/api/v1/projects/'+me.projects[0].id+'/runs')).json();
 const run=runs.find(r=>r.question==='V1.2本地受控验收：事实归因与逐条依据');
 const analysis=await (await context.request.get(base+'/api/v1/analyses/'+run.analysis_id)).json();
 assert.equal(analysis.provider_metadata.quality_contract,'v12-claims-1');
 page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/v1/projects/*/runs',r=>r.request().method()==='POST'?r.abort():r.continue());
 await page.goto(base,{waitUntil:'networkidle'});
 await page.getByRole('button',{name:'跳过',exact:true}).click();
 await page.getByRole('button',{name:run.question,exact:true}).click();
 const reasons=page.getByLabel('本次原因分项');await reasons.waitFor();
 const text=await reasons.innerText();
 for(const label of ['14日消耗缺日 · 1 个组合','库存快照超过24小时 · 1 个组合','完整14日零消耗记录 · 1 个组合','反应杯','采样管'])assert.ok(text.includes(label),label);
 checks.push('reason counts and named positions remain separate');
 assert.match(await page.getByLabel('服务端风险分级').innerText(),/高关注\s*3\s*条.*中关注\s*5\s*条/);checks.push('existing risk counts preserved');
 await page.getByText(`逐条依据 · ${analysis.claims.length} 条`,{exact:true}).click();
 const ledger=page.getByLabel('逐条结论与依据');await ledger.waitFor();
 await settle();
 for(const label of ['工具事实匹配','原文匹配','待人工核实'])assert.ok((await ledger.innerText()).includes(label),label);
 checks.push('fact quote advice and unknown labels displayed');
 await page.screenshot({path:output+'claims-desktop.png'});
 const fact=analysis.claims.find(c=>c.kind==='fact');
 const toolResponse=page.waitForResponse(r=>r.url().endsWith('/evidence/'+fact.evidence_ids[0])&&r.status()===200);
 await page.getByRole('button',{name:`查看${fact.id}的依据1`,exact:true}).click();
 const tool=await (await toolResponse).json();assert.equal(tool.source_kind,'tool');assert.equal(tool.facts.risks.scanned_positions,24);
 assert.deepEqual(tool.facts.reason_breakdown,analysis.reason_breakdown);
 await page.getByRole('dialog').last().getByText('授权范围异常扫描',{exact:true}).waitFor();checks.push('fact button opens actual immutable tool evidence');
 await page.keyboard.press('Escape');await settle();
 const policy=analysis.claims.find(c=>c.kind==='policy');
 const docResponse=page.waitForResponse(r=>r.url().endsWith('/evidence/'+policy.evidence_ids[0])&&r.status()===200);
 await page.getByRole('button',{name:`查看${policy.id}的依据1`,exact:true}).click();
 const doc=await (await docResponse).json();assert.equal(doc.source_kind,'document');assert.ok(doc.excerpt.includes(policy.text));
 await page.getByRole('dialog').last().locator('.evidence-excerpt').waitFor();
 assert.ok((await page.getByRole('dialog').last().locator('.evidence-excerpt').innerText()).includes(policy.text));checks.push('quoted policy opens matching original excerpt');
 await settle();await page.screenshot({path:output+'policy-source.png'});await page.keyboard.press('Escape');await settle();
 await page.setViewportSize({width:390,height:844});
 await ledger.waitFor();await settle();const dimensions=await page.evaluate(()=>({client:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth}));
 assert.equal(dimensions.client,dimensions.scroll);
 const box=await ledger.boundingBox();assert.ok(box.x>=0&&box.x+box.width<=390,JSON.stringify(box));
 await page.screenshot({path:output+'claims-mobile.png',fullPage:true});checks.push('390px claim ledger stays within viewport');
 await page.keyboard.press('Escape');await page.getByRole('button',{name:'历史流程兼容核查',exact:true}).click();
 await page.getByText('历史流程校验记录',{exact:true}).waitFor();assert.equal(await page.getByLabel('本次原因分项').count(),0);
 assert.equal(await page.getByLabel('逐条结论与依据').count(),0);checks.push('legacy history receives no invented verification');
 assert.deepEqual(errors,[]);
 await fs.writeFile(output+'browser-results.json',JSON.stringify({kind:'isolated_browser_controlled_provider',real_model_calls:0,cloud_uploads:0,checks,errors,dimensions},null,2)+'\n');console.log(JSON.stringify({checks,errors,dimensions}));
} catch(e) {
 if(page){await page.screenshot({path:output+`browser-${attempt}-failure.png`,fullPage:true});await fs.writeFile(output+`browser-${attempt}-page.txt`,await page.locator('body').innerText());}
 await fs.writeFile(output+`browser-${attempt}-failure.json`,JSON.stringify({checks,errors,error:String(e)},null,2)+'\n');throw e;
} finally {await browser.close();}
