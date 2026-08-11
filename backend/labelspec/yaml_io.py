from __future__ import annotations

from typing import Dict

import yaml

from .domain import CompiledStandard


def standard_to_yaml_files(standard: CompiledStandard) -> Dict[str, str]:
    options = {"allow_unicode": True, "sort_keys": False, "width": 100}
    return {
        "labels.yaml": yaml.safe_dump(standard.labels.model_dump(), **options),
        "definition_rules.yaml": yaml.safe_dump(
            [rule.model_dump() for rule in standard.definition_rules], **options
        ),
        "decision_rules.yaml": yaml.safe_dump(standard.decision_rules.model_dump(), **options),
    }

