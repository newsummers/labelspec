from __future__ import annotations

import json

from .domain import AnnotationDecision, DisclosureTrace
from .provider import QianfanProvider


ANNOTATOR_SYSTEM = """你是 LabelSpec Annotator，执行单标签文本分类。
你必须逐项完成 Definition、Exclude、候选 Label、Boundary、Priority、规则充分性检查。
rules_used 只能填写输入中真实存在且实际参与判断的 Rule ID；rule_reasons 必须解释每条 Rule 如何影响判断。
若现有规则不能唯一决定标签，禁止强行分类：
- 两个或多个标签都能被规则合理支持时 ambiguous=true；
- 标准未规定当前情形或规则冲突无法消解时 spec_gap=true；
- 规则大体充分但需要历史人工 Case 才能稳定判断时 needs_history=true。
输出严格符合 JSON Schema。"""


def _trace_prompt(text: str, trace: DisclosureTrace) -> str:
    return "\n\n".join(
        [
            f"待标注文本：{text}",
            "候选标签：\n" + json.dumps(trace.candidates, ensure_ascii=False),
            "候选 Definition Rules：\n" + json.dumps(
                [rule.model_dump() for rule in trace.definitions], ensure_ascii=False
            ),
            "相关 Boundary Rules：\n" + json.dumps(
                [rule.model_dump() for rule in trace.boundaries], ensure_ascii=False
            ),
            "全局 Priority Rules：\n" + json.dumps(
                [rule.model_dump() for rule in trace.global_priority_rules], ensure_ascii=False
            ),
            "历史人工确认 Case：\n" + json.dumps(trace.historical_cases, ensure_ascii=False),
        ]
    )


async def annotate(
    provider: QianfanProvider,
    model: str,
    text: str,
    trace: DisclosureTrace,
) -> AnnotationDecision:
    return await provider.structured(
        model=model,
        system=ANNOTATOR_SYSTEM,
        user=_trace_prompt(text, trace),
        response_model=AnnotationDecision,
        temperature=0.05,
    )

