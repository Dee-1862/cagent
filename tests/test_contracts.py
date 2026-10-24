import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from contracts.models import CONTRACTS, AnomalyEvent

EXAMPLES = Path(__file__).resolve().parent.parent / "contracts" / "examples"


def load_example(name: str) -> dict:
    return json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def test_every_contract_has_an_example():
    assert {p.stem for p in EXAMPLES.glob("*.json")} == set(CONTRACTS)


@pytest.mark.parametrize("name", sorted(CONTRACTS))
def test_example_matches_contract(name):
    CONTRACTS[name].model_validate(load_example(name))


def test_unknown_fields_are_rejected():
    event = load_example("AnomalyEvent")
    event["surprise"] = 1
    with pytest.raises(ValidationError):
        AnomalyEvent.model_validate(event)


def test_local_hint_kind_is_restrictive_or_none():
    event = load_example("AnomalyEvent")
    event["local_hint"]["kind"] = "permissive"
    with pytest.raises(ValidationError):
        AnomalyEvent.model_validate(event)
