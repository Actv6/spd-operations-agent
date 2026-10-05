"""Bounded output guards. These checks do not prove sentence-level entailment."""
import re
import unicodedata
from .errors import AppError


def risk_summary(report):
    return {"scanned_positions": report["scanned_positions"], "skipped_estimates": report["skipped_estimates"],
            **report["estimate_gap_counts"], "findings": len(report["findings"])}


def risk_priority_summary(report):
    findings = report["findings"]
    return {
        "high": sum(1 for row in findings if row.get("priority") == "high"),
        "medium": sum(1 for row in findings if row.get("priority") == "medium"),
    }


def count_value(text):
    """Parse bounded Chinese integer counts; never ask the model to recount."""
    if text.isdecimal():
        return int(text)
    digits = dict(zip('零〇一二两三四五六七八九', [0, 0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9]))
    if all(c in digits for c in text):
        return int(''.join(str(digits[c]) for c in text))
    total, current = 0, 0
    for char in text:
        if char in digits:
            current = digits[char]
        else:
            total += (current or 1) * {'十': 10, '百': 100, '千': 1000}[char]
            current = 0
    return total + current


def priority_mentions(text, labels):
    text = unicodedata.normalize('NFKC', text)
    text = re.sub(r'[*_`#]', '', text)
    number = r'[0-9零〇一二两三四五六七八九十百千]+'
    label = '(?:' + '|'.join(labels) + ')'
    glue = r'\s*(?:风险|异常|事项|项目|数量|条数|项数)?\s*[：:=（(]?\s*(?:(?:共有|总共|合计|共计|共|为|有|是)\s*){0,2}'
    forward = re.findall(label + glue + '(' + number + r')\s*(?:条|项|个|处|[）)])', text)
    reverse = re.findall('(' + number + r')\s*(?:条|项|个|处)\s*(?:属于|为|是)?\s*' + label, text)
    return [count_value(v) for v in forward + reverse]


def validate_business_answer(answer, expected_summary, codes, require_scan=False, expected_priority_counts=None):
    if require_scan and expected_summary is None:
        raise AppError("RISK_SCAN_REQUIRED", "全范围核查未完成实际异常扫描，请重新核查", 502)
    if expected_summary is not None:
        if answer.risk_summary is None or answer.risk_summary.model_dump() != expected_summary:
            raise AppError("RISK_SUMMARY_MISMATCH", "扫描计数与工具事实不一致", 502)
        if expected_priority_counts is not None:
            # Defense in depth for known count expressions, not arbitrary entailment.
            labels = {
                "high": ['高关注', '优先核实', '高优先级'],
                "medium": ['中关注', '一般关注', '中优先级'],
            }
            for level, names in labels.items():
                mentions = priority_mentions(answer.answer, names)
                if any(value != expected_priority_counts[level] for value in mentions):
                    raise AppError("RISK_PRIORITY_COUNT_MISMATCH", "正文关注级别数量与扫描结果不一致", 502)
    elif answer.risk_summary is not None:
        raise AppError("RISK_SUMMARY_UNSUPPORTED", "没有扫描依据，不能生成风险汇总", 502)
    text = answer.answer + ("\n" + answer.task_draft.title + "\n" + "\n".join(answer.task_draft.steps) if answer.task_draft else "")
    if re.search(r'(?:知识库|项目资料)(?:中|内)?(?:不存在|没有任何|完全没有)|(?:不存在|没有任何)(?:相关|适用)(?:资料|制度|依据)', text):
        raise AppError('KNOWLEDGE_ABSENCE_OVERCLAIM', '检索不能证明资料不存在，请表述为本次未检索到适用资料', 502)
    unknown = set(re.findall(r"(?<![A-Za-z0-9_])MAT-[A-Za-z0-9-]+", text)) - set(codes)
    if unknown:
        raise AppError("ANSWER_CODE_INVALID", "回答含未核实的物资编码", 502)
    if re.search(r"(?<![A-Za-z0-9_])(?:SIM-[A-Za-z0-9-]+|(?:get|compute|search)_[a-z_]+|skipped_estimates|scanned_positions|estimate_gap_counts|coverage_days|daily_average|observed_days|days_to_expiry|source_rows|task_draft|evidence_ids|insufficient_evidence|risk_summary|complete\s*=|[A-Z]+_[A-Z_]+)(?![A-Za-z0-9_])", text):
        raise AppError("ANSWER_LANGUAGE_INVALID", "请用业务名称和中文状态说明，内部字段保留在证据中", 502)


def recorded_tokens(metadata):
    """Unknown usage stays unknown in stored metadata, not fabricated as zero."""
    return sum((m.get("usage") or {}).get("total_tokens") or 0 for m in metadata)


def no_advice_requested(question):
    """Recognize explicit current-question limits, not arbitrary semantic intent."""
    question = unicodedata.normalize('NFKC', question)
    explicit = re.search(r'(?:不要|不给|不提供|不需要|无需|别)(?:再|给出|提供|给|任何|追加|附加|的|\s)*(?:处理)?(?:建议|行动清单|处理步骤)', question)
    only_dates = re.search(r'只(?:回答|答|说|列出|给出)(?:一下|出|我|\s)*(?:缺失的|缺失|消耗缺失的|消耗缺失)?日期', question)
    return bool(explicit or only_dates)


def validate_answer_scope(question, text):
    """Reject known affirmative action instructions when explicitly forbidden."""
    if not no_advice_requested(question):
        return
    normalized = unicodedata.normalize('NFKC', text)
    normalized = re.sub(r'[*_`#]', '', normalized)
    for clause in re.split(r'[。！？；，\n]', normalized):
        clause = clause.strip()
        heading = re.match(r'^(?:\d+[.、)]\s*)?(?:处理建议|行动清单|下一步建议|处理步骤)\s*[:：]?$', clause)
        actions = re.finditer(r'(?:建议|请|应当|应该|务必|需要|应)(?:先|直接|尽快|及时|重新|由|人工|再|予以|\s)*(?:核对|核实|补齐|发布|提交|联系|安排|采购|处理|确认|查阅)', clause)
        # Check negation locally for each instruction, so "不能补零但建议
        # 核对" is not incorrectly exempted as an entirely negative clause.
        affirmative = any(not re.search(r'(?:不|无需|勿|别|不能)\s*$', clause[:match.start()]) for match in actions)
        if heading or affirmative:
            raise AppError('ANSWER_SCOPE_VIOLATION', '用户限定不提供建议，请只回答指定事实与原因', 502)
