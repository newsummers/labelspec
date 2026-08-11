from __future__ import annotations

from .domain import CompiledStandard
from .provider import QianfanProvider


COMPILER_SYSTEM = """你是 LabelSpec 标准编译器。你的任务是把业务标准编译为可执行的单标签文本分类规则。

必须遵循：
1. 保留业务含义，不臆造与原文冲突的政策。
2. 每个标签有唯一名称和一句可快速扫描的 description。
3. 每个标签恰好对应一个 Definition Rule，ID 从 D001 连续编号。
4. 标签存在容易混淆的边界时创建 Boundary Rule，ID 从 B001 连续编号。
5. 抽取全局分类原则为 Priority Rule，ID 从 P001 连续编号。
6. Definition 必须包含 definition、include、exclude、positive_examples、negative_examples；原文不足时可给保守的空列表。
7. Boundary Rule 的 labels 必须引用标签目录中的完整标签名。
8. 只支持单标签文本分类。
9. 输出必须严格符合 JSON Schema，不要输出解释性文字。
"""


async def compile_standard(
    provider: QianfanProvider, model: str, name: str, source_markdown: str
) -> CompiledStandard:
    prompt = f"""标准名称：{name}

请编译以下业务标准：

---
{source_markdown.strip()}
---
"""
    compiled = await provider.structured(
        model=model,
        system=COMPILER_SYSTEM,
        user=prompt,
        response_model=CompiledStandard,
        temperature=0.05,
    )
    compiled.name = name
    return compiled

