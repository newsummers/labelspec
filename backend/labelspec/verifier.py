from __future__ import annotations

import json

from .domain import AnnotationDecision, DisclosureTrace, VerificationDecision
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
