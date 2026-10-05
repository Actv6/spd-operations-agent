const { chromium } = require('/Users/ac/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
(async () => {
  const browser = await chromium.launch({headless:true, executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const page = await browser.newPage({viewport:{width:1440,height:960}});
  const errors=[]; page.on('pageerror',e=>errors.push(e.message));
  const origin='http://127.0.0.1:4181';
  const csrf=(await (await page.request.get(origin+'/api/v1/csrf')).json()).token;
  const r=await page.request.post(origin+'/api/v1/registrations',{headers:{Origin:origin,'X-CSRF-Token':csrf},data:{email:`layout-${Date.now()}@example.test`,password:'layout-test-password',display_name:'布局验收'}});
  assert.equal(r.status(),201);
  await page.goto(origin+'/app/imports');
  await page.getByRole('button',{name:'新建导入',exact:true}).click();
  await page.getByRole('button',{name:'下载模板',exact:true}).first().waitFor();
  const results=[];
  async function check(state,width,height) {
    await page.setViewportSize({width,height});
    await page.screenshot({path:`${__dirname}/${state}-${width}.png`,fullPage:true,animations:'disabled'});
    const geometry=await page.evaluate(()=>{
      const cards=[...document.querySelectorAll('.csv-upload')];
      const rect=e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,height:r.height};};
      return {cards:cards.map(card=>({card:rect(card),zone:rect(card.querySelector('.ant-upload-drag,.csv-upload-file'))})),guide:rect(document.querySelector('.import-guide')),overflow:document.documentElement.scrollWidth>innerWidth};
    });
    for(const {card,zone} of geometry.cards) {
      assert(zone.bottom <= card.bottom-8, `${state}/${width}: upload zone outside card`);
      assert(zone.left >= card.left && zone.right <= card.right, `${state}/${width}: horizontal card overflow`);
      assert(zone.height < 180, `${state}/${width}: oversized upload zone`);
    }
    assert(geometry.guide.top >= Math.max(...geometry.cards.map(r=>r.card.bottom)),`${state}/${width}: rules overlap cards`);
    assert.equal(geometry.overflow,false);
    results.push({state,width,height,geometry});
  }
  for(const width of [1440,939,800,390]) await check('empty',width,width===390?844:960);
  const cards=page.getByRole('region',{name:/文件上传/});
  await cards.nth(0).locator('input[type=file]').setInputFiles({name:'inventory.csv',mimeType:'text/csv',buffer:Buffer.from('物资编码,科室\nMAT-0001,检验科\n')});
  await cards.nth(0).getByText('已读取，待校验').waitFor();
  for(const width of [1440,390]) await check('mixed',width,width===390?844:960);
  for(let i=1;i<3;i++) {
    await cards.nth(i).locator('input[type=file]').setInputFiles({name:`data-${i}.csv`,mimeType:'text/csv',buffer:Buffer.from('物资编码,科室\nMAT-0001,检验科\n')});
    await cards.nth(i).getByText('已读取，待校验').waitFor();
  }
  for(const width of [1440,390]) await check('selected',width,width===390?844:960);
  assert.deepEqual(errors,[]);
  fs.writeFileSync(`${__dirname}/results.json`,JSON.stringify({checks:results,page_errors:errors},null,2));
  await browser.close(); console.log(`Passed ${results.length} layout checks`);
})().catch(e=>{console.error(e);process.exit(1);});
