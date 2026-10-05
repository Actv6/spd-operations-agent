// Static dependency-closure sizes, not a network or device timing benchmark.
import fs from 'node:fs';
import zlib from 'node:zlib';
const root = new URL('../dist/client/', import.meta.url);
const manifest = JSON.parse(fs.readFileSync(new URL('.vite/manifest.json', root)));
const entry = Object.keys(manifest).find(k => manifest[k].isEntry);
function closure(keys) {
  const seen = new Set();
  const visit = k => { if (seen.has(k)) return; seen.add(k); for (const dep of manifest[k].imports || []) visit(dep); };
  keys.forEach(visit); return [...seen];
}
function key(name) {
  const result = Object.keys(manifest).find(k => manifest[k].isDynamicEntry && manifest[k].name === name);
  if (!result) throw new Error(`Missing dynamic entry: ${name}`);
  return result;
}
const report = {};
for (const [name, names] of Object.entries({entry:[], login:['Auth'], workspace:['Workspace'], risks:['Workspace','RiskPanel'], knowledge:['Workspace','KnowledgePanel'], analysis:['Workspace','ResultPanel','RunActions']})) {
  const assets = closure([entry,...names.map(key)]).map(k=>manifest[k].file).filter(f=>f.endsWith('.js'));
  report[name] = {js_bytes:0,gzip_bytes:0,assets};
  for (const f of assets) { const data = fs.readFileSync(new URL(f, root)); report[name].js_bytes += data.length; report[name].gzip_bytes += zlib.gzipSync(data).length; }
}
report.notes = ['Static JS dependency closure; excludes CSS/images; not measured latency.', 'Analysis includes follow-up and draft UI dependencies.', 'Earlier Vite main JS: 1394.59 kB / gzip 444.57 kB.'];
const output = process.argv[2];
if (output) fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(Object.fromEntries(Object.entries(report).filter(([k])=>k!=='notes').map(([k,v])=>[k,{js_bytes:v.js_bytes,gzip_bytes:v.gzip_bytes}]))));
