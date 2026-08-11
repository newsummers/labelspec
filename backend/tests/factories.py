from labelspec.domain import CompiledStandard


def standard() -> CompiledStandard:
    return CompiledStandard.model_validate(
        {
            "name": "测试标准",
            "labels": {
                "labels": [
                    {"name": "金融/贷款", "description": "个人贷款"},
                    {"name": "汽车/购车", "description": "汽车购买"},
                ]
            },
            "definition_rules": [
                {
                    "rule_id": "D001",
                    "label": "金融/贷款",
                    "definition": "贷款问题",
                    "include": ["利率"],
                    "exclude": ["车型"],
                    "positive_examples": ["贷款利率"],
                    "negative_examples": ["买什么车"],
                },
                {
                    "rule_id": "D002",
                    "label": "汽车/购车",
                    "definition": "购车决策",
                    "include": ["车型"],
                    "exclude": ["贷款利率"],
                    "positive_examples": ["买什么车"],
                    "negative_examples": ["贷款利率"],
                },
            ],
            "decision_rules": {
                "boundary_rules": [
                    {
                        "rule_id": "B001",
                        "labels": ["金融/贷款", "汽车/购车"],
                        "condition": "同时涉及购车和贷款",
                        "decision": "核心诉求是利率则选贷款，否则选购车",
                    }
                ],
                "priority_rules": [
                    {"rule_id": "P001", "principle": "最终诉求优先于实体行业"}
                ],
            },
        }
    )

