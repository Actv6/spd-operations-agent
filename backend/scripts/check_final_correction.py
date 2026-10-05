"""One live correction of an immutable recorded answer; never writes its source DB."""
import asyncio
import json
import sqlite3
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.providers import DeepSeekProvider
from app.schemas import ModelAnswer
from app.answer_quality import validate_business_answer
from app.errors import AppError

if '--live' not in sys.argv:
    raise SystemExit('Explicit --live is required; no request')

source = Path('../docs/verification/m21-quality3-20260928/live-20260928-145844.json')
record = next(r for r in json.loads(source.read_text())['cases'] if r['case']=='draft')
used_before = 88410
if used_before >= 90000 or record['tokens_recorded'] >= 20000:
    raise SystemExit('Recorded token stop threshold reached; no request')
con = sqlite3.connect('file:var/evals/m21-20260928-145844.db?mode=ro',uri=True)
checkpoint = json.loads(con.execute('select checkpoint from agent_runs where id=?',(record['run_id'],)).fetchone()[0])
answer = ModelAnswer(answer=record['analysis']['answer'], evidence_ids=[c['evidence_id'] for c in record['analysis']['citations']], insufficient_evidence=record['analysis']['insufficient_evidence'], task_draft={k:record['draft'][k] for k in ['title','steps']})
try:
    validate_business_answer(answer,None,['MAT-0006'])
except AppError as exc:
    assert exc.body['code']=='ANSWER_LANGUAGE_INVALID'
else:
    raise SystemExit('Recorded answer did not trigger expected guard; no request')
messages = checkpoint['messages'] + [
    {'role':'system','content':'最终回答聚焦最后一条用户问题，历史只用于指代。本次模式为draft_action。草稿建议在task_draft.steps列出，answer简短说明事实与待确认状态即可，不重复整份步骤。'},
    {'role':'assistant','content':answer.model_dump_json()},
    {'role':'user','content':'上次输出未通过校验（ANSWER_LANGUAGE_INVALID）。只允许纠正一次：按Schema返回JSON，正确转义。risk_summary逐值使用服务端汇总；零消耗不归为数据质量错误。中文正文用业务名称，不出现内部SIM编号、字段或工具名；MAT编码必须与目录一致。保持证据ID，不补造事实，简洁回答当前问题。'}]
start=time.monotonic()
message,meta=asyncio.run(DeepSeekProvider(Settings()).complete(messages,final=True))
fixed=ModelAnswer.model_validate_json(message['content'])
validate_business_answer(fixed,None,['MAT-0006'])
assert set(fixed.evidence_ids) <= {c['evidence_id'] for c in record['analysis']['citations']}
assert fixed.task_draft and fixed.evidence_ids
result={'kind':'single_final_correction_not_full_run','source':str(source),'source_run_id':record['run_id'],'initial_error':'ANSWER_LANGUAGE_INVALID','corrected':fixed.model_dump(),'metadata':meta,'elapsed_seconds':round(time.monotonic()-start,2),'tokens_before':used_before,'tokens_after':used_before+(meta.get('usage') or {}).get('total_tokens',0),'source_db_modified':False,'tasks_created':0}
out=Path('../docs/verification/m21-quality-final-20260928/correction.json');out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
