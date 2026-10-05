const {chromium} = require('/Users/ac/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs = require('fs'); const cp = require('child_process'); const assert = require('assert/strict');
const out=__dirname;
(async () => {
 const browser = await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const page = await browser.newPage({viewport:{width:1440,height:960}});
 const errors=[]; page.on('pageerror',e=>errors.push(e.message));
 const origin='http://127.0.0.1:4181';
 const csrf=(await (await page.request.get(origin+'/api/v1/csrf')).json()).token;
 const response=await page.request.post(origin+'/api/v1/registrations',{headers:{Origin:origin,'X-CSRF-Token':csrf},data:{email:`import-${Date.now()}@example.test`,password:'upload-acceptance-password',display_name:'导入验收'}});
 assert.equal(response.status(),201,await response.text());
 const project=(await response.json()).projects[0].id;
 const before=await (await page.request.get(`${origin}/api/v1/projects/${project}/dashboard`)).json();
 await page.goto(origin+'/app/imports');
 await page.getByRole('button',{name:'新建导入',exact:true}).waitFor({timeout:60000});
 await page.getByRole('button',{name:'新建导入',exact:true}).click();
 await page.getByRole('button',{name:'下载模板',exact:true}).first().waitFor({timeout:30000});
 await page.screenshot({path:out+'/01-desktop-empty.png',fullPage:true,animations:"disabled"});
 const labels=['库存','批次','消耗'], kinds=['inventory','batches','consumption'];
 for(let i=0;i<3;i++) {
   const download=page.waitForEvent('download');
   await page.getByRole('button',{name:'下载模板',exact:true}).nth(i).click();
   await (await download).saveAs(`${out}/${kinds[i]}-template.csv`);
 }
 cp.execFileSync('/Users/ac/Documents/ChatGPT/agent项目学习/backend/.venv/bin/python',[out+'/fill-fixtures.py']);
 const card=label=>page.getByRole('region',{name:label+'文件上传'});
 const primary=page.getByRole('button',{name:'校验并生成预览',exact:true});
 assert(await primary.isDisabled());
 await card('库存').locator('input[type=file]').setInputFiles({name:'wrong.xlsx',mimeType:'application/octet-stream',buffer:Buffer.from('wrong')});
 await card('库存').getByRole('alert').filter({hasText:'请选择 CSV'}).waitFor();
 await page.screenshot({path:out+'/02-wrong-format.png',fullPage:true,animations:"disabled"});
 await card('库存').locator('input[type=file]').setInputFiles({name:'oversized.csv',mimeType:'text/csv',buffer:Buffer.alloc(10*1024*1024+1,97)});
 await card('库存').getByRole('alert').filter({hasText:'超过 10MB'}).waitFor();
 await card('库存').locator('input[type=file]').setInputFiles({name:'invalid-utf8.csv',mimeType:'text/csv',buffer:Buffer.from([0xff])});
 await card('库存').getByRole('alert').filter({hasText:'UTF-8'}).waitFor();
 // Slow only local slice reads to make progress/cancellation observable; API responses remain real.
 await page.evaluate(()=>{const original=Blob.prototype.arrayBuffer;window.__originalArrayBuffer=original;Blob.prototype.arrayBuffer=async function(){await new Promise(r=>setTimeout(r,50));return original.call(this);};});
 await card('库存').locator('input[type=file]').setInputFiles({name:'reading-large.csv',mimeType:'text/csv',buffer:Buffer.alloc(9*1024*1024,97)});
 await card('库存').getByText('正在读取文件，尚未提交服务器').waitFor();
 assert(await primary.isDisabled());
 await page.screenshot({path:out+'/03-read-progress.png',fullPage:true,animations:"disabled"});
 await card('库存').getByRole('button',{name:'取消读取库存文件',exact:true}).click();
 await page.waitForTimeout(200);
 assert.equal(await card('库存').getByText('点击选择或拖拽文件').count(),1);
 await page.evaluate(()=>{Blob.prototype.arrayBuffer=window.__originalArrayBuffer;});
 for(let i=0;i<3;i++) {
   await card(labels[i]).locator('input[type=file]').setInputFiles(`${out}/${kinds[i]}${i===1?'-large':''}-filled.csv`);
   await card(labels[i]).getByText('已读取，待校验').waitFor();
 }
 await page.getByText('已准备 3/3 个文件 · 校验不会改变当前数据').waitFor();
 assert(!(await primary.isDisabled()));
 await page.screenshot({path:out+'/04-filled-desktop.png',fullPage:true,animations:"disabled"});
 await page.setViewportSize({width:390,height:844}); await page.waitForTimeout(400);
 await page.screenshot({path:out+'/05-filled-mobile.png',fullPage:true,animations:"disabled"});
 const footer=page.locator('.import-footer');
 console.log('Mobile footer', await footer.boundingBox()); assert((await footer.boundingBox()).x>=-1);
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false);
 await page.setViewportSize({width:1440,height:960});
 const post=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith(`/projects/${project}/imports`));
 await primary.click();
 const validationResponse=await post; const job=await validationResponse.json();
 fs.writeFileSync(out+'/preview-response.json',JSON.stringify(job,null,2));
 assert.equal(validationResponse.status(),201); assert.equal(job.status,'ready'); assert.equal(job.error_count,0);
 assert(job.changes.some(x=>x.kind==='changed'));
 await page.getByText('校验与快照预览',{exact:true}).waitFor();
 await page.screenshot({path:out+'/06-preview-desktop.png',fullPage:true,animations:"disabled"});
 const after=await (await page.request.get(`${origin}/api/v1/projects/${project}/dashboard`)).json();
 assert.equal(after.snapshot_set_id,before.snapshot_set_id);
 // Returning to upload must require all files again, not submit invisible retained values.
 await page.getByRole('button',{name:'重新上传',exact:true}).click();
 await page.getByText('已准备 0/3 个文件 · 校验不会改变当前数据').waitFor();
 assert(await primary.isDisabled());
 fs.writeFileSync(out+'/browser-results.json',JSON.stringify({database:'isolated SQLite',provider_calls:0,template_downloads:3,filled_uploads:3,preview_status:job.status,errors:job.error_count,warnings:job.warning_count,current_snapshot_unchanged:true,format_size_encoding_checks:true,cancel_and_stale_read_checks:true,return_to_upload_reset:true,desktop_and_390px:true,page_errors:errors},null,2));
 assert.deepEqual(errors,[]);
 await browser.close(); console.log('Import browser acceptance passed');
})().catch(e=>{fs.writeFileSync(out+'/browser-failure.txt',e.stack); console.error(e);process.exit(1);});
