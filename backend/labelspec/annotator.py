from __future__ import annotations

import json
from typing import Optional

from .domain import AnnotationDecision, DisclosureTrace
from .provider import QianfanProvider


ANNOTATOR_SYSTEM = """你是 LabelSpec Annotator，执行单标签文本分类。
每个候选叶子标签都以「层级定义链」的形式给出：从根类目到叶子逐层列出 Definition，层级递进、由粗到细。
你的任务是输出一个可审计的结论，而不是汇报检查步骤。
- 无论是否确定，都必须从输入候选中选择一个完整的叶子标签路径；label 和 leaf_rule_used 是必填项。
- 能依据现有规则唯一分类且证据充分时，needs_review=false。
- 存在多个合理候选、标准覆盖不足、规则冲突、需要上下文或信心不足时，仍然选择最合理的标签，并将 needs_review=true，填写 review_reason_codes 和可读的 reason。
- status 仅为兼容旧数据，始终输出 LABELED。
decision_rules_referenced 只填写实际改变或消解当前结论的 Boundary / Priority Rule；没有适用规则时保持空数组。
rule_reasons 逐条解释 decision_rules_referenced 中的 Rule 如何影响结论。
evidence 必须引用或紧贴原文中的事实，不要把规则复述当作文本证据。
evidence_items 逐条记录文本事实、Definition、Boundary、Priority 依据；每条规则依据都要包含 rule_id、rule_text 和 explanation。
reason 用正常人能看懂的一段话说明为什么选择该标签，以及为什么需要或不需要人工审核。
输出严格符合 JSON Schema。"""


def _render_chain(chain) -> str:
    lines = [f"候选叶子路径：{chain.leaf_path}"]
    depth = len(chain.chain)
    for level, rule in enumerate(chain.chain, start=1):
        indent = "  " * level
        role = "叶子·最终判定层" if level == depth else f"第{level}层·上位类目"
        lines.append(
            f"{indent}第{level}层 {rule.rule_id}（{role}）：{rule.definition}"
            f"\n{indent}  include: {json.dumps(rule.include, ensure_ascii=False)}"
            f"\n{indent}  exclude: {json.dumps(rule.exclude, ensure_ascii=False)}"
        )
    return "\n".join(lines)


def _trace_prompt(
    text: str, trace: DisclosureTrace, correction: Optional[str] = None
) -> str:
    single_candidate = len(trace.definitions) == 1
    task_hint = (
        "当前只有 1 个候选叶子。你的任务是核实该文本是否符合这一个叶子的层级定义链；"
        "如果定义不完全匹配，也必须选择唯一候选并 needs_review=true，在 reason 中说明缺口。"
        if single_candidate
        else "请在下列候选叶子中选择 1 个；如果存在歧义或规则缺口，选择最合理者并标记 needs_review=true。"
    )
    sections = [
        f"待标注文本：{text}",
        task_hint,
        "候选叶子层级定义链：\n"
        + "\n\n".join(_render_chain(chain) for chain in trace.definitions),
        "相关 Boundary Rules：\n" + json.dumps(
            [rule.model_dump() for rule in trace.boundaries], ensure_ascii=False
        ),
        "全局 Priority Rules：\n" + json.dumps(
            [rule.model_dump() for rule in trace.global_priority_rules], ensure_ascii=False
        ),
        "历史人工确认 Case：\n" + json.dumps(trace.historical_cases, ensure_ascii=False),
    ]
    if correction:
        sections.append("输出纠正要求：\n" + correction)
    return "\n\n".join(sections)


async def annotate(
    provider: QianfanProvider,
    model: str,
    text: str,
    trace: DisclosureTrace,
    correction: Optional[str] = None,
) -> AnnotationDecision:
    return await provider.structured(
        model=model,
        system=ANNOTATOR_SYSTEM,
        user=_trace_prompt(text, trace, correction),
        response_model=AnnotationDecision,
        temperature=0.05,
    )
