from labelspec.domain import CompiledStandard


def standard() -> CompiledStandard:
    return CompiledStandard.model_validate(
        {
            "schema_version": "0.2",
            "name": "测试标准",
            "labels": {
                "labels": [
                    {"label_id": "L001", "name": "金融", "description": "金融业务", "parent_id": None},
                    {"label_id": "L002", "name": "贷款", "description": "个人贷款", "parent_id": "L001"},
                    {"label_id": "L003", "name": "汽车", "description": "汽车业务", "parent_id": None},
                    {"label_id": "L004", "name": "购车", "description": "汽车购买", "parent_id": "L003"},
                ]
            },
            "definition_rules": [
                {"rule_id": "D001", "label_id": "L001", "definition": "金融相关服务", "include": ["贷款"]},
                {
                    "rule_id": "D002", "label_id": "L002", "definition": "借款、利率、额度、还款等贷款诉求",
                    "include": ["贷款利率"], "exclude": ["买车价格"],
                    "include": ["贷款利率是多少"], "exclude": ["这辆车多少钱"],
                },
                {"rule_id": "D003", "label_id": "L003", "definition": "汽车相关服务", "include": ["购车"]},
                {
                    "rule_id": "D004", "label_id": "L004", "definition": "车型、价格、配置等购车诉求",
                    "include": ["车型价格"], "exclude": ["贷款利率"],
                    "include": ["这辆车多少钱"], "exclude": ["贷款年利率是多少"],
                },
            ],
            "decision_rules": {
                "boundary_rules": [
                    {
                        "rule_id": "B001", "label_ids": ["L002", "L004"],
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
