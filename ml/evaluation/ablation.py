"""Replay fixed validation tracks; freeze selection before separate test evaluation."""

import argparse
import json
import sys
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services/api"))
from sentinel.rules import RuleEngine, Track  # noqa: E402
from sentinel.schemas import Rule  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("fixture", type=Path, help="JSON {rules,zones,frames:[{timestamp,tracks}],scope}")
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
fixture = json.loads(args.fixture.read_text())
fixture["rules"] = [{**Rule.model_validate(r).model_dump(), "id": r["id"]} for r in fixture["rules"]]
results = []
for persistence, confidence, sample_every, exit_grace in product(
    (0, 0.5, 1, 2), (0.25, 0.5), (1, 2), (0, 0.5)
):
    rules = [{**r, "persistence": persistence, "exit_grace": exit_grace} for r in fixture["rules"]]
    engine = RuleEngine(rules, fixture["zones"])
    events = []
    for frame in fixture["frames"][::sample_every]:
        events.extend(
            engine.step(
                frame["timestamp"], [Track(**t) for t in frame["tracks"] if t["confidence"] >= confidence]
            )
        )
    results.append(
        {
            "persistence": persistence,
            "confidence": confidence,
            "sample_every": sample_every,
            "exit_grace": exit_grace,
            "events": events,
        }
    )
args.output.write_text(
    json.dumps({"scope": fixture.get("scope", "unvalidated input"), "ablations": results}, indent=2)
)
