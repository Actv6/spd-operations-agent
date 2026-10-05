"""Bounded deterministic support checks; suggestions are never semantic proof."""
import re
import unicodedata
from decimal import Decimal
from .data import canonical_hash
from .errors import AppError
from .answer_quality import count_value

RELEASE = 'v12-claims-1'
LABELS = {
    'MISSING_CONSUMPTION_DAYS': '14日消耗缺日',
    'STALE_SNAPSHOT': '库存快照超过24小时',
    'INVALID_BATCH_QUANTITY': '批次数量异常',
    'MISSING_BATCHES': '缺少批次',
    'UNSUPPORTED_CONSUMPTION': '消耗记录待核实',
    'DUPLICATE_CONSUMPTION_DAY': '消耗日期重复',
    'ZERO_CONSUMPTION': '完整14日零消耗记录',
}
TAGS = {'fact': '已核实事实', 'policy': '资料原文', 'suggestion': '建议（待人工核实）', 'unknown': '待确认'}


def row_reasons(row):
    reasons = set(row['quality_issues'])
    if not reasons and row['daily_average'] is not None and Decimal(row['daily_average']) == 0:
        reasons.add('ZERO_CONSUMPTION')
    return reasons


def reason_breakdown(rows, evidence_id):
    # One position may belong to multiple groups. Do not sum into unique totals.
    unique = {(r['item_id'], r['department_id']): r for r in rows}
    return [{'reason': code, 'label': label,
             'count': len(members), 'positions': members, 'evidence_ids': [evidence_id]}
            for code, label in LABELS.items()
            if (members := [{k: r[k] for k in ('item_id', 'department_id', 'name', 'department_name')}
                            for r in unique.values() if code in row_reasons(r)])]


def fact_catalog(kind, data, rows, evidence_id):
    """Only describes the executed tool result, never a new hidden query."""
    facts = []
    def add(key, text):
        facts.append({'fact_id': 'f-' + canonical_hash([evidence_id, key])[:20],
                      'text': text, 'evidence_ids': [evidence_id]})
    names = {(r['item_id'], r['department_id']): f"{r['name']} · {r['department_name']}" for r in rows}
    if kind == 'risks':
        add('scan', f"本次扫描{data['scanned_positions']}个物资科室组合，发现{len(data['findings'])}条关注事项。")
        add('gaps', f"覆盖基线暂不可估算共{data['skipped_estimates']}个物资科室组合，其中数据待核查{data['estimate_gap_counts']['data_quality']}个、完整14日零消耗记录{data['estimate_gap_counts']['zero_consumption']}个。")
        high = sum(f['priority'] == 'high' for f in data['findings'])
        add('priority', f"高关注{high}条，中关注{len(data['findings']) - high}条。")
        for group in reason_breakdown(rows, evidence_id):
            members = '、'.join(f"{p['name']} · {p['department_name']}" for p in group['positions'])
            add(group['reason'], f"{group['label']}：{group['count']}个物资科室组合（{members}）。")
        for finding in data['findings']:
            add(finding['id'], f"{finding['name']} · {finding['department_name']}：{finding['summary']}。")
    elif kind == 'inventory':
        for row in data:
            key = (row['item_id'], row['department_id'])
            metrics = '，'.join(f"{label}{row[field]}{unit}" if row[field] is not None else f"{label}暂不可估算"
                               for field, label, unit in [('available', '可用库存', row['unit']), ('daily_average', '日均消耗', row['unit']), ('coverage_days', '覆盖基线', '天')])
            add([key, 'metrics'], f"{names[key]}：{metrics}。")
            reasons = row_reasons(row)
            if reasons:
                add([key, 'reasons'], f"{names[key]}：{'、'.join(LABELS.get(q, q) for q in sorted(reasons))}。")
    elif kind == 'consumption':
        for row in data:
            key = (row['item_id'], row['department_id'])
            add([key, 'observed'], f"{names[key]}：14日窗口内已记录{row['observed_days']}天。")
            for status, label in [('missing', '缺失日期（未补零）'), ('invalid', '待核实日期')]:
                dates = [d['date'] for d in row['days'] if d['status'] == status]
                if dates:
                    add([key, status], f"{names[key]}：{label}为{'、'.join(dates)}。")
            if row['daily_average'] is not None:
                add([key, 'average'], f"{names[key]}：14日日均消耗记录为{row['daily_average']}{row['unit']}。")
    elif kind == 'batches':
        for row in data:
            key = (row['product_id'], row['department_id'])
            add(row['id'], f"{names[key]}：批次{row['id']}的到期日期为{row['expiry_date']}，相对快照业务日剩余{row['days_to_expiry']}天，在库{row['on_hand']}{row['unit']}。")
    return facts


def render_claims(claims):
    return '\n\n'.join(f"{TAGS[c.kind]}：{c.text}" for c in claims)


def validate_claims(answer, catalog, sources):
    if not answer.claims:
        raise AppError('CLAIMS_REQUIRED', '新核查须提供逐条结论与依据关联', 502)
    known = {f['fact_id']: f for f in catalog}
    views = []
    used = set()
    for i, claim in enumerate(answer.claims):
        refs = set(claim.evidence_ids)
        if len(refs) != len(claim.evidence_ids) or refs - sources.keys():
            raise AppError('CLAIM_CITATION_INVALID', '逐条引用不在本轮实际证据中', 502)
        if claim.kind == 'fact':
            fact = known.get(claim.fact_ids[0]) if len(claim.fact_ids) == 1 else None
            if not fact or claim.text != fact['text'] or refs != set(fact['evidence_ids']):
                raise AppError('CLAIM_FACT_MISMATCH', '事实、对象、数值与本轮事实目录不一致', 502)
            verification = 'tool_exact'
        else:
            if claim.fact_ids:
                raise AppError('CLAIM_KIND_INVALID', '非事实段落不能冒用事实核验标记', 502)
            if claim.kind == 'policy':
                if len(refs) != 1 or not all(sources[e]['source_kind'] == 'document' and
                        claim.text in sources[e]['excerpt'] for e in refs):
                    raise AppError('CLAIM_QUOTE_MISMATCH', '资料原文必须逐字匹配本轮文档摘录', 502)
                verification = 'document_quote'
            else:
                if claim.kind == 'suggestion' and not refs:
                    raise AppError('CLAIM_SUGGESTION_UNGROUNDED', '建议需关联本轮核查来源，仍须人工核实', 502)
                if claim.kind == 'unknown' and not answer.insufficient_evidence:
                    raise AppError('CLAIM_UNKNOWN_STATUS', '待确认信息须标记依据不足', 502)
                verification = 'unverified'
        used |= refs
        views.append({'id': f'claim-{i + 1}', **claim.model_dump(), 'verification': verification})
    if set(answer.evidence_ids) != used:
        raise AppError('CLAIM_CITATION_COVERAGE', '总引用须与逐条实际引用一致', 502)
    if answer.answer != render_claims(answer.claims):
        raise AppError('CLAIM_ANSWER_MISMATCH', '正文须逐段对应结论，不得另加无关联事实', 502)
    if answer.task_draft:
        suggestions = {c.text for c in answer.claims if c.kind == 'suggestion'}
        if set(answer.task_draft.steps) - suggestions:
            raise AppError('CLAIM_DRAFT_MISMATCH', '草稿步骤须对应已标记待人工核实的建议', 502)
    return views


REASON_PATTERNS = {
    'MISSING_CONSUMPTION_DAYS': r'(?:消耗(?:记录)?缺日|缺日|用量漏填|消耗记录缺失)',
    'STALE_SNAPSHOT': r'(?:旧快照|快照过期|库存快照超过24小时|库存记录超过24小时)',
    'ZERO_CONSUMPTION': r'(?:零消耗(?:记录)?|14日(?:消耗)?全零)',
    'INVALID_BATCH_QUANTITY': r'批次数量异常',
    'MISSING_BATCHES': r'缺少批次',
    'UNSUPPORTED_CONSUMPTION': r'消耗记录待核实',
    'DUPLICATE_CONSUMPTION_DAY': r'消耗日期重复',
}
NUMBER = r'[0-9零〇一二两三四五六七八九十百千]+'


def validate_reason_text(text, rows):
    """Known affirmative reason counts/objects; not arbitrary entailment."""
    text = re.sub(r'[*_`#]', '', unicodedata.normalize('NFKC', text))
    for clause in re.split(r'[。！？；，!?;,\n]|(?:但是|但)', text):
        for code, pattern in REASON_PATTERNS.items():
            matches = list(re.finditer(pattern, clause))
            if not matches:
                continue
            # Exempt locally negated reasons, not an entire mixed clause.
            positive = [m for m in matches if not re.search(r'(?:不是|并非|不属于|没有|未出现|不等于)\s*$', clause[:m.start()])]
            if not positive:
                continue
            eligible = [r for r in rows if code in row_reasons(r)]
            forward = re.finditer(pattern + r'\s*[：:]?\s*(?:(?:数量|物资|位置|组合|记录)\s*)?(?:(?:共有|共计|总共|合计|共|为|有|是)\s*)?(' + NUMBER + r')\s*(个|项|处|种)', clause)
            reverse = re.finditer('(' + NUMBER + r')\s*(个|项|处|种)(?:(?:物资科室组合|位置|物资|记录|因|由于|是|为|有|存在|14日|十四日|消耗|记录|的|\s))*' + pattern, clause)
            for match in list(forward) + list(reverse):
                if re.search(r'(?:不是|并非|不等于)\s*$', clause[:match.start()]):
                    continue
                count, unit = match.group(1), match.group(2)
                expected = len({r['item_id'] for r in eligible}) if unit == '种' else len({(r['item_id'], r['department_id']) for r in eligible})
                if count_value(count) != expected:
                    raise AppError('QUALITY_REASON_MISATTRIBUTION', '原因数量与本轮物资科室事实不一致', 502)
            named = [r for r in rows if r['name'] in clause or (r.get('display_code') and r['display_code'] in clause)]
            departments = {r['department_name'] for r in rows if r['department_name'] and r['department_name'] in clause}
            if departments:
                named = [r for r in named if r['department_name'] in departments]
            if named and any(code not in row_reasons(r) for r in named):
                raise AppError('QUALITY_REASON_OBJECT_MISMATCH', '原因归属与所指物资科室不一致，请明确对象', 502)
