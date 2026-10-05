import json
from typing import Protocol
import httpx
from .tracing import model_input
from .errors import AppError
from .schemas import InventoryArgs, SearchArgs, ModelAnswer


PROMPT_RELEASE = "v12-claims-1"


class EmbeddingProvider(Protocol):
    model: str
    dimensions: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


TOOLS = [{"type": "function", "function": {"name": name, "description": description, "parameters": schema.model_json_schema()}}
         for name, description, schema in [
             ("get_inventory", "查询当前授权快照的库存和14天消耗；只读，空筛选代表本次运行许可范围", InventoryArgs),
             ("get_batches", "查询批次效期；超过3个物资科室位置先返回全部位置摘要，逐批明细请缩小范围。空筛选沿用许可范围", InventoryArgs),
             ("get_consumption", "查询快照前14日消耗；超过3个位置返回日均与缺日摘要，逐日明细请缩小范围；缺失不是零", InventoryArgs),
             ("compute_risks", "按确定性阈值扫描本次授权范围的全部库存、效期和数据缺口，返回覆盖计数", InventoryArgs),
             ("search_knowledge", "在当前项目有效文档中执行中文词法检索，返回可引用片段", SearchArgs),
         ]]


class DeepSeekProvider:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.transport = transport

    async def complete(self, messages, final=False):
        s = self.settings
        if not s.deepseek_api_key:
            raise AppError("PROVIDER_NOT_CONFIGURED", "DeepSeek 尚未配置服务端 API key", 503)
        wire_messages = list(messages)
        if final:
            # A new explicit request avoids continuing the assistant's free-form draft.
            wire_messages.append({"role": "user", "content": "现在结束工具调用，整理最终结果。只返回一个 JSON 对象，不要 Markdown 代码围栏、前言或额外字段。JSON字符串中的换行、引号和反斜杠必须转义，不能含未转义控制字符。answer 必须是中文字符串（可含 Markdown 分段），evidence_ids 必须是实际工具证据 ID 的字符串数组，仅列确实支持结论的来源，insufficient_evidence 必须是布尔值。若仍缺回答问题所需的关键资料则为 true。只回答当前用户问题；用户明确要求简短或只回答指定内容时优先遵守，不追加与本题无关的风险免责声明。仅列影响当前结论的关键缺口。区分工具中的记录事实、引用明确支持的制度要求和你提出的建议；建议须标明“建议”，不得增造单据形式、出具人或审批要求。已执行风险扫描时，按工具实际范围表述已完成的效期筛查，不得因未读取逐批明细而称未做效期检查。未发现规则命中不等于无任何风险，也不必机械追加这句话。仅当系统指定任务模式为 draft_action 时，必须提供 task_draft 对象（title、steps），描述待人工核实的内部事项，不声称已执行采购/报废等操作。其余模式 task_draft=null。严格符合以下 JSON Schema：" + json.dumps(ModelAnswer.model_json_schema(), ensure_ascii=False)})
        payload = {"model": s.deepseek_model, "messages": wire_messages, "stream": False, "thinking": {"type": "disabled"}, "max_tokens": 1800}
        if final:
            payload["response_format"] = {"type": "json_object"}
        else:
            payload["tools"] = TOOLS
        model_input(payload)
        input_chars = len(json.dumps(payload, ensure_ascii=False))
        if input_chars > s.max_input_chars:
            raise AppError("CONTEXT_BUDGET_EXCEEDED", "本次查询内容超过输入预算，请缩小物资范围后重新核查", 422)
        try:
            async with httpx.AsyncClient(timeout=min(s.run_timeout_seconds, 25), transport=self.transport) as client:
                response = await client.post(s.deepseek_base_url.rstrip("/") + "/chat/completions", headers={"Authorization": f"Bearer {s.deepseek_api_key}"}, json=payload)
            if response.status_code == 429:
                raise AppError("PROVIDER_RATE_LIMITED", "模型服务限流，请稍后新建运行", 503, True)
            if response.status_code >= 400:
                raise AppError("PROVIDER_ERROR", f"模型服务请求失败（HTTP {response.status_code}）", 503, response.status_code >= 500)
            body = response.json()
            choice = body["choices"][0]
            if choice.get("finish_reason") == "length":
                raise AppError("MODEL_OUTPUT_TRUNCATED", "模型输出被截断", 502)
            message = choice["message"]
            if not isinstance(message, dict) or not (message.get("content") or message.get("tool_calls")):
                raise ValueError("empty response")
            # Never persist or expose raw reasoning fields.
            return {"role": "assistant", "content": message.get("content"), **({"tool_calls": message["tool_calls"]} if message.get("tool_calls") else {})}, {
                "prompt_release": PROMPT_RELEASE, "requested_model": s.deepseek_model, "response_model": body.get("model"), "usage": body.get("usage"), "input_chars": input_chars, "cost": None, "provider_version": body.get("system_fingerprint")}
        except httpx.TimeoutException:
            raise AppError("PROVIDER_TIMEOUT", "模型服务超时", 503, True)
        except httpx.RequestError:
            raise AppError("PROVIDER_UNAVAILABLE", "模型服务网络不可用", 503, True)
        except (ValueError, KeyError, IndexError, TypeError):
            raise AppError("MODEL_OUTPUT_INVALID", "模型响应结构无效", 502)


class MockProvider:
    async def complete(self, messages, final=False):
        outputs = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        if not final and not outputs:
            question = next(m["content"] for m in messages if m["role"] == "user")
            return {"role": "assistant", "content": None, "tool_calls": [
                {"id": "mock_inventory", "type": "function", "function": {"name": "get_inventory", "arguments": json.dumps({"item_ids": [], "department_ids": []})}},
                {"id": "mock_knowledge", "type": "function", "function": {"name": "search_knowledge", "arguments": json.dumps({"query": question}, ensure_ascii=False)}},
            ]}, {"usage": None, "cost": None}
        evidence = [eid for o in outputs for eid in o["evidence_ids"]]
        documents = [o for o in outputs if o.get("kind") == "knowledge" and o["data"]]
        answer = "离线演示已实际查询授权库存，并检索有效资料。请结合下方确定性库存指标与原文核查；此文字由 mock 模板生成。" if documents else "未检索到支持该问题的有效制度依据，无法给出制度结论。库存查询结果可在下方核查。此文字由 mock 模板生成。"
        return {"role": "assistant", "content": json.dumps({"answer": answer, "evidence_ids": evidence, "insufficient_evidence": not bool(documents)}, ensure_ascii=False)}, {"usage": None, "cost": None}


def provider_for(settings, name):
    return MockProvider() if name == "mock" else DeepSeekProvider(settings)
