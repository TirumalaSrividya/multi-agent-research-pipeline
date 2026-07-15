#!/usr/bin/env bash
# Verifies every report JSON in outputs/ against:
#   1. the pydantic ResearchReport schema (types + word/score bounds)
#   2. every citation resolves to a real source_id in that same report
#   3. no duplicate report_ids across the whole output directory
#   4. confidence_score / relevance_score values are within [0.0, 1.0]
#
# Exits non-zero (and prints the failures) if anything is wrong.
set -euo pipefail

OUTPUT_DIR="${1:-outputs}"

python3 - "$OUTPUT_DIR" << 'PYEOF'
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
from src.schemas import ResearchReport  # noqa: E402

output_dir = Path(sys.argv[1])
report_files = sorted(output_dir.glob("*.json"))
report_files = [f for f in report_files if not f.name.endswith(".trace.json")]

if not report_files:
    print(f"FAIL: no report files found in {output_dir}")
    sys.exit(1)

errors = []
seen_report_ids = set()
checked = 0

for path in report_files:
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        errors.append(f"{path.name}: invalid JSON ({e})")
        continue

    # 1. schema validity
    try:
        report = ResearchReport(**raw)
    except Exception as e:  # noqa: BLE001
        errors.append(f"{path.name}: schema validation failed: {e}")
        continue

    # 2. citation integrity
    source_ids = {s.source_id for s in report.sources}
    for section in report.sections:
        for cid in section.citations:
            if cid not in source_ids:
                errors.append(f"{path.name}: section '{section.heading}' cites unknown source_id '{cid}'")

    # 3. duplicate report_id detection
    if report.report_id in seen_report_ids:
        errors.append(f"{path.name}: duplicate report_id '{report.report_id}'")
    seen_report_ids.add(report.report_id)

    # 4. score ranges (pydantic already enforces this, but double check explicitly)
    if not (0.0 <= report.critique.confidence_score <= 1.0):
        errors.append(f"{path.name}: confidence_score out of range: {report.critique.confidence_score}")
    for s in report.sources:
        if not (0.0 <= s.relevance_score <= 1.0):
            errors.append(f"{path.name}: relevance_score out of range for {s.source_id}")

    checked += 1

print(f"Checked {checked} report(s) in {output_dir}")
if errors:
    print(f"\nFAIL: {len(errors)} issue(s) found:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)

print("PASS: all reports valid, all citations resolve, no duplicate report_ids, all scores in range.")
PYEOF
