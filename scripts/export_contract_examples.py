"""Write one JSON example per contract into contracts/examples/ (milestone M0).

Run from the repo root: python scripts/export_contract_examples.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from unstep.contracts import Envelope  # noqa: E402
from unstep.scenario import ALL_EXAMPLES  # noqa: E402

out_dir = ROOT / "contracts" / "examples"
out_dir.mkdir(parents=True, exist_ok=True)

for msg in ALL_EXAMPLES:
    name = type(msg).__name__
    env = Envelope(type=name, ts=0, data=msg.model_dump(mode="json"))
    (out_dir / f"{name}.json").write_text(json.dumps(env.model_dump(mode="json"), indent=2) + "\n")
    print(f"wrote contracts/examples/{name}.json")
