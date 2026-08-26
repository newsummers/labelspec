from __future__ import annotations

import json

from .domain import (
    AnnotationDecision,
    CompiledStandard,
    DisclosureTrace,
    TraceReplica,
    VerificationDecision,
)
from .provider import QianfanProvider


VERIFIER_SYSTEM = """你是独立的 LabelSpec Verifier。你的职责不是重做标注，而是寻找足以阻止自动通过的具体反证。
只核验 status=LABELED 的结论：
1. 文本是否不满足最终叶子 Definition；
2. 是否命中最终标签的 Exclude；
3. 已披露候选中是否存在明显更合适的标签；
4. 是否遗漏了会改变结论的 Boundary / Priority Rule；
5. Annotator 的 evidence 是否无法由原文支撑。
对应 issue code 只能使用 DEFINITION_MISMATCH、EXCLUDE_HIT、BETTER_CANDIDATE、MISSED_DECISION_RULE、UNGROUNDED_EVIDENCE 或 OTHER。
只有可能改变标签或证明证据不足的问题才标记 BLOCKING；不影响结论的提示标记 WARNING。
没有具体问题时 outcome=PASS、issues=[]。存在 BLOCKING issue 时 outcome=REVIEW，并准确说明 Rule ID 和原因。
规则虽然被披露但对当前文本不适用，不算遗漏。不要因为没有 Boundary / Priority Rule 而制造问题。
outcome 不得使用 SKIPPED。输出严格符合 JSON Schema。"""

TRACE_VERIFIER_SYSTEM = """你是 LabelSpec 的多 Trace Verifier。你会看到同一个 query 的多次独立标注 Trace。
比较 Trace 并仲裁最终合法叶子标签，同时诊断无法稳定决定的原因。
diagnosis 只能是 CONSENSUS、MAJORITY、MULTI_INTENT、UNCLEAR_EXPRESSION、SPEC_GAP 或 INVALID。
MULTI_INTENT 必须返回多个 labels 并人工审核；UNCLEAR_EXPRESSION 可以推测 inferred_intent 但必须人工审核；SPEC_GAP 表示意图清晰但标准覆盖不足，必须填写 inferred_intent 和 standard_feedback。
standard_feedback.suggestion_type 只能是 DEFINITION、BOUNDARY 或 PRIORITY。
只能从三条 Trace 候选的并集中选择合法叶子标签；如果候选并集不足以覆盖意图，输出 SPEC_GAP 或 INVALID，不要创造标签。
CONSENSUS 或 MAJORITY 也必须检查 Definition、Exclude、Boundary 和 Priority 依据。输出严格符合 JSON Schema。"""


async def verify(
    provider: QianfanProvider,
    model: str,
    text: str,
    trace: DisclosureTrace,
    decision: AnnotationDecision,
) -> VerificationDecision:
    prompt = {
        "text": text,
        "annotation": decision.model_dump(),
        "candidate_definition_chains": [chain.model_dump() for chain in trace.definitions],
        "boundary_rules": [rule.model_dump() for rule in trace.boundaries],
        "priority_rules": [rule.model_dump() for rule in trace.global_priority_rules],
        "historical_cases": trace.historical_cases,
    }
    return await provider.structured(
        model=model,
        system=VERIFIER_SYSTEM,
        user=json.dumps(prompt, ensure_ascii=False),
        response_model=VerificationDecision,
        temperature=0.0,
    )


async def verify_traces(
    provider: QianfanProvider,
    model: str,
    text: str,
    traces: list[TraceReplica],
    standard: CompiledStandard,
) -> VerificationDecision:
    """Adjudicate independent traces for one query."""
    candidate_union = sorted({candidate for trace in traces for candidate in trace.candidates})
    prompt = {
        "text": text,
        "candidate_union": candidate_union,
        "traces": [trace.model_dump(mode="json") for trace in traces],
        "standard_context": {
            "labels": [label.model_dump(mode="json") for label in standard.labels.labels],
            "boundary_rules": [rule.model_dump(mode="json") for rule in standard.decision_rules.boundary_rules],
            "priority_rules": [rule.model_dump(mode="json") for rule in standard.decision_rules.priority_rules],
        },
    }
    return await provider.structured(
        model=model,
        system=TRACE_VERIFIER_SYSTEM,
        user=json.dumps(prompt, ensure_ascii=False),
        response_model=VerificationDecision,
        temperature=0.0,
    )
