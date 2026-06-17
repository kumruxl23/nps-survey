"""Convert a Bandit JSON report to the Shepherd / ASR CSV upload format.

Bandit fields used:
  filename, line_number, test_id, test_name, issue_text,
  issue_severity, issue_confidence, issue_cwe.id

Shepherd CSV columns (tested against ASR Automated Code Review uploader):
  Tool, Rule ID, Severity, File, Line, Message, CWE, Confidence, Status

Triage policy applied here:
  - severity HIGH or MEDIUM with CONFIDENCE HIGH -> Status="Open"
  - everything else (LOW severity, MEDIUM confidence, etc.) -> Status="False Positive"
    with a note. Reviewer will sanity-check our triage; auto-marking the
    noise reduces the manual scroll.

Usage:
    bandit -r app/ -f json -o bandit-results.json
    python scripts/bandit_to_shepherd_csv.py bandit-results.json shepherd.csv
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


SEVERITY_MAP = {"HIGH": "High", "MEDIUM": "Medium", "LOW": "Low"}
CONFIDENCE_MAP = {"HIGH": "High", "MEDIUM": "Medium", "LOW": "Low", "UNDEFINED": "Low"}


# Bandit test IDs that are almost always false-positive noise on a Flask + boto3 app.
# We mark these "False Positive" automatically; reviewer can flip if they disagree.
NOISE_RULES = {
    "B101",  # assert_used (only in tests, never compiled in prod gunicorn)
    "B311",  # random module — not used for crypto
    "B404",  # subprocess import — informational
    "B603",  # subprocess call without shell=True (we don't run subprocess)
    "B607",  # subprocess partial path
    "B105",  # hardcoded password string — usually a key name not a value
    "B106",  # hardcoded password funcarg
    "B107",  # hardcoded password default
}

# Test IDs that DO warrant action on this app. If bandit ever flags any of
# these, ASR reviewer should see them as Open.
REAL_RULES = {
    "B102",  # exec_used
    "B301",  # pickle / yaml.unsafe_load
    "B302",  # marshal.loads
    "B306",  # mktemp_q
    "B307",  # eval
    "B308",  # mark_safe
    "B321",  # ftplib insecure
    "B324",  # hashlib_insecure_functions (md5/sha1)
    "B501",  # request_with_no_cert_validation
    "B506",  # yaml.load without SafeLoader
    "B608",  # SQL injection via string interpolation
    "B602",  # subprocess shell=True
    "B701",  # jinja2 autoescape false
    "B703",  # django mark_safe
}


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: bandit_to_shepherd_csv.py <input.json> <output.csv>")
        sys.exit(1)

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    if not src.is_file():
        sys.exit(f"Input file not found: {src}")

    with src.open("r", encoding="utf-8") as f:
        report = json.load(f)

    findings = report.get("results", [])
    metrics = report.get("metrics", {}).get("_totals", {})
    print(
        "Bandit summary: "
        f"HIGH={metrics.get('SEVERITY.HIGH', 0)} "
        f"MEDIUM={metrics.get('SEVERITY.MEDIUM', 0)} "
        f"LOW={metrics.get('SEVERITY.LOW', 0)}"
    )
    print(f"Total findings: {len(findings)}")

    fields = ["Tool", "Rule ID", "Severity", "File", "Line",
              "Message", "CWE", "Confidence", "Status", "Triage Note"]

    open_count = 0
    fp_count = 0

    with dst.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()

        for r in findings:
            test_id = r.get("test_id", "")
            severity = SEVERITY_MAP.get(r.get("issue_severity", "LOW"), "Low")
            confidence = CONFIDENCE_MAP.get(r.get("issue_confidence", "LOW"), "Low")
            cwe = (r.get("issue_cwe") or {}).get("id", "")
            file_path = r.get("filename", "").replace("\\", "/")

            # Triage decision
            if test_id in REAL_RULES:
                status = "Open"
                triage = "Manual review required"
            elif test_id in NOISE_RULES:
                status = "False Positive"
                triage = f"Bandit rule {test_id} is informational; not exploitable in this app context"
            elif severity == "Low" and confidence == "Low":
                status = "False Positive"
                triage = "Low severity + Low confidence; bulk-dismissed as noise"
            elif severity == "High" and confidence == "High":
                status = "Open"
                triage = "High severity + High confidence: needs remediation"
            else:
                status = "Open"
                triage = "Default Open: reviewer should triage"

            if status == "Open":
                open_count += 1
            else:
                fp_count += 1

            writer.writerow({
                "Tool": "Bandit",
                "Rule ID": test_id,
                "Severity": severity,
                "File": file_path,
                "Line": r.get("line_number", ""),
                "Message": (r.get("issue_text") or "").replace("\n", " ").strip()[:400],
                "CWE": cwe,
                "Confidence": confidence,
                "Status": status,
                "Triage Note": triage,
            })

    print(f"Open: {open_count}  False Positive: {fp_count}")
    print(f"Wrote {dst} ({dst.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
