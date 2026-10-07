"""Apply the predeclared development gates; never select using regression results."""

import argparse
import json
from pathlib import Path

from refundguard.corpus import sha256


def development_decision(metrics, criteria):
    checks = {
        "answerable_coverage": metrics["answerable_coverage"]["value"] is not None
        and metrics["answerable_coverage"]["value"] >= criteria["minimum_answerable_coverage"],
        "citation_precision": metrics["citation_correctness"]["value"] is not None
        and metrics["citation_correctness"]["value"]
        >= criteria["minimum_gold_label_citation_precision"],
        "unknown_abstention": metrics["unanswerable_abstention_rate"]["value"]
        == criteria["required_unknown_abstention_rate"],
        "model_outputs_blocked": metrics["model_outputs_blocked"]
        <= criteria["maximum_model_outputs_blocked"],
    }
    return {
        "eligible_for_promotion": all(checks.values()),
        "checks": checks,
        "failed_gates": [name for name, passed in checks.items() if not passed],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=Path("config/model_comparison.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.report.read_bytes()
    report = json.loads(raw)
    protocol = json.loads(args.protocol.read_text())
    if report["split"] != "dev":
        raise ValueError("Model selection requires development data, not regression results")
    if report["model_lock_sha256"] != protocol["candidate_lock_sha256"]:
        raise ValueError("Candidate lock differs from the predeclared comparison")
    if (
        report["replay"]["retrieval_report_sha256"]
        != protocol["retrieval_report_sha256"]["reports/explanation_v2/dev.json"]
    ):
        raise ValueError("Development retrieval differs from the predeclared snapshot")
    decision = development_decision(report["metrics"], protocol["development_promotion_criteria"])
    output = {
        **decision,
        "selection_source": "Original development only",
        "development_report_sha256": sha256(raw),
        "predeclared_protocol_sha256": sha256(args.protocol.read_bytes()),
        "criteria": protocol["development_promotion_criteria"],
        "metrics": report["metrics"],
        "default_files_modified_by_this_command": False,
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(decision, indent=2))


if __name__ == "__main__":
    main()
