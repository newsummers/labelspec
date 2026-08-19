from __future__ import annotations

import json
from typing import Optional

from .domain import AnnotationDecision, DisclosureTrace
from .provider import QianfanProvider


ANNOTATOR_SYSTEM = """你是 LabelSpec Annotator，执行单标签文本分类。
每个候选叶子标签都以「层级定义链」的形式给出：从根类目到叶子逐层列出 Definition，层级递进、由粗到细。
你必须逐层核对该文本是否满足链上每一层的 Definition，最终仅依据链末端的叶子 Definition 做出判定。
leaf_rule_used 只能填写你最终采纳的那个候选叶子的 rule_id（链的最后一层），且必须真实存在于输入中；
path_rules_referenced 用于记录你在推理过程中参考过的祖先层 rule_id（链的中间层），仅作留痕，不是判定依据。
decision_rules_referenced 用于记录实际参与判断的 Boundary / Priority Rule ID；不适用的规则不要填写。
label 必须与 leaf_rule_used 对应的候选叶子路径完全一致，禁止编造或截断路径。
rule_reasons 必须解释每条被引用的 Rule（包含以上三类 Rule）如何影响判断。
若现有规则不能唯一决定标签，禁止强行分类：
- 两个或多个候选叶子都能被规则合理支持时 ambiguous=true；
- 标准未规定当前情形或规则冲突无法消解时 spec_gap=true；
- 规则大体充分但需要历史人工 Case 才能稳定判断时 needs_history=true。
ambiguous 或 spec_gap 为 true 时，label 与 leaf_rule_used 必须留空。
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
        "如果不符合，禁止强行分类，应通过 spec_gap 或 missing_rule_reason 说明原因，label 留空。"
        if single_candidate
        else "请在下列候选叶子中选择 1 个（或判定 ambiguous/spec_gap），依据各自的层级定义链逐层核对。"
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
