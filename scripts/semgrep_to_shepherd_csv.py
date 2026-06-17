"""Convert a Semgrep JSON report to the CSV format Shepherd / ASR expect.

Usage:
    semgrep --config=p/python --config=p/flask --config=p/secrets \\
        --json -o semgrep-results.json app/
    python scripts/semgrep_to_shepherd_csv.py semgrep-results.json shepherd.csv

Output columns (matching Shepherd's bulk-import template):
    Tool, Rule ID, Severity, File, Line, Message, CWE, Confidence, Status
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


SEVERITY_MAP = {
    "ERROR": "High",
    "WARNING": "Medium",
    "INFO": "Low",
}


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: semgrep_to_shepherd_csv.py <input.json> <output.csv>")
        sys.exit(1)

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])

    if not src.is_file():
        sys.exit(f"Input file not found: {src}")

    with src.open("r", encoding="utf-8") as f:
        report = json.load(f)

    findings = report.get("results", [])
    print(f"Found {len(findings)} Semgrep finding(s)")

    fields = ["Tool", "Rule ID", "Severity", "File", "Line",
              "Message", "CWE", "Confidence", "Status"]

    with dst.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()

        for r in findings:
            extra = r.get("extra") or {}
            metadata = extra.get("metadata") or {}
            cwe_raw = metadata.get("cwe") or ""
            if isinstance(cwe_raw, list):
                cwe_raw = ", ".join(str(c) for c in cwe_raw)

            confidence = (metadata.get("confidence") or "MEDIUM").title()

            writer.writerow({
                "Tool": "Semgrep",
                "Rule ID": r.get("check_id", ""),
                "Severity": SEVERITY_MAP.get(extra.get("severity", "INFO"), "Low"),
                "File": r.get("path", ""),
                "Line": (r.get("start") or {}).get("line", ""),
                "Message": (extra.get("message") or "").replace("\n", " ").strip(),
                "CWE": cwe_raw,
                "Confidence": confidence,
                "Status": "Open",
            })

    print(f"Wrote {dst} ({dst.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
