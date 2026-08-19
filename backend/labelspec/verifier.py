from __future__ import annotations

import json

from .domain import AnnotationDecision, DisclosureTrace, VerificationDecision
from .provider import QianfanProvider


VERIFIER_SYSTEM = """你是独立的 LabelSpec Verifier。不要默认 Annotator 正确。
核验最终标签是否被叶子 Definition 支持、是否触发 Exclude、leaf_rule_used 是否真实存在且适用、是否遗漏已披露的 Boundary / Priority Rule，以及证据是否足以支撑结论。
path_rules_referenced 是 Annotator 参考的上位类目定义，仅用于理解推理路径，不作为 unsupported_rules 的核验对象。
decision_rules_referenced 是 Annotator 明确采用的 Boundary / Priority Rule。
omitted_* 只填写对当前判断确实适用但被 Annotator 遗漏的 Rule ID。
verdict 只能是 PASS、UNCERTAIN、REJECT。输出严格符合 JSON Schema。"""


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
