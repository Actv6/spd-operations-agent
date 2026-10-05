"""Reproduce generated onsite fixtures and versioned field collection notes."""
import hashlib
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.onsite import build, BUNDLE, RELEASE

NOTES = {
 'HANDOVER': ('驻场晨间交接与采集记录', '驻场交接按科室登记物资编码、基础单位、在库、冻结、预留、批号、效期和记录时间。数量分别由科室台账与实物核查，差异保留原因和待核查项。交接需区分记录业务时间与上传时间，不把旧台账作为实时库存。', '消耗按前14个完整自然日采集，显式零与缺失记录分开登记；本次扩展包含急诊、重症医学科、血液透析室、消毒供应中心、内科病区。交接记录不含患者身份、诊疗信息或真实工作人员姓名。'),
 'SHORTAGE': ('驻场缺料反馈与配送核查记录', '急诊一次性输液器与内科病区鼻氧管存在短覆盖场景。驻场专员先核对基础单位、科室现有量与近14日消耗，再向供应端核实到货日和配送数量。未经确认的在途不得计入确定供应。', '科室提出的临时需求独立登记需求时间、物资编码、需求数量和用途类别，不以日均消耗自动代替订单。系统给出核查建议，采购和库存扣减另由业务系统办理。'),
 'EXPIRY': ('驻场临期批次与冻结核查记录', '无菌注射器、血液透析管路、鼻氧管的部分批次设置12天后到期，供核查先到期先发出、剩余数量和科室需求。批次最后可用日须从包装核对，临期提示不等于报废。', '部分批次保留冻结或预留数量。冻结核对质量隔离原因，预留核对科室需求；两者不重复占用同一数量。解冻、调拨和处置不能通过完成个人任务自动执行。'),
 'RECON': ('驻场库存与日消耗对账记录', '按物资科室组合核对在库、冻结和预留与批次汇总，所有数量使用档案基础单位。本次新增每个组合均保留14个完整自然日的逐日消耗，旧数据中的缺日问题保留。', '多科室共用物资必须分科室登记。输液器、留置针、注射器、隔离衣、纱布块、鼻氧管分别设置两个科室位置；跨科室数量不得混作单科室可用库存。'),
}

def main():
 BUNDLE.mkdir(parents=True, exist_ok=True)
 def write(path,value):
  path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
 write(BUNDLE/'facts.json', build('SIM-HA', '2026-09-27T09:00:00+08:00'))
 manifest=[]
 for key,(title,a,b) in NOTES.items():
  content=f'# {title}\n\n版本：1.0　业务基准：2026-09-27\n\n## 现场核查范围\n{a}\n\n## 交接与闭环\n{b}\n'
  path=f'ONS-{key}-v1.md'
  (BUNDLE/path).write_text(content)
  manifest.append(dict(id=f'ONS-{key}-v1',title=title,version='1.0',status='approved_demo',effective_from='2026-09-27',effective_until=None,allowed_hospitals=['SIM-HA','SIM-HB'],path=path,sha256=hashlib.sha256(content.encode()).hexdigest(),synthetic=True,source_type='generated_hospital_onsite_scenario'))
 write(BUNDLE/'manifest.json',manifest)
 write(BUNDLE/'provenance.json',dict(release=RELEASE,synthetic=True,real_company_data=False,source='Generated onsite collection scenario; no real hospital file supplied',business_as_of='2026-09-27T09:00:00+08:00'))
 print('Generated: 12 products, 4 departments, 18 placements, 36 batches, 252 daily records, 4 documents')
if __name__ == '__main__':
 main()
