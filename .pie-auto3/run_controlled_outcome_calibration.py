from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from review_system.evaluation import load_evaluation_report, run_evaluation, write_evaluation_report
from review_system.github.source import refresh_source_hash
from review_system.github_prospective_capture import (
    build_github_prospective_capture_candidate,
    write_github_prospective_capture_candidate,
)
from review_system.identity import canonical_json_sha256
from review_system.intelligence_graph import calculate_graph_sha256
from review_system.io import dump_json, dump_yaml, load_data
from review_system.trust import assess_trust, write_trust_report
from review_system.trust_comparison import load_registry, new_registry, write_registry
from review_system.trust_outcome_declaration import build_outcome_declaration
from review_system.trust_outcome_transport import transport_declared_outcome
from review_system.trust_prospective_evidence import campaign_progress, intake_prospective_case
from review_system.trust_prospective_review import (
    prepare_review_packet,
    submit_review_packet,
    write_review_packet,
)


PROJECT_ID = "auto3-controlled-calibration"
REPOSITORY = "pie-peb3-lab/pie-peb3-calibration"
CHANGED_PATH = "src/auto3_calibration.py"
ACTOR = "synthetic:auto3-calibration-human"
CREATED_AT = "2026-08-24T05:10:00Z"
CAPTURE_AT = "2026-08-24T05:14:00Z"
PACKET_AT = "2026-08-24T05:15:00Z"
REVIEW_AT = "2026-08-24T05:16:00Z"
DECLARED_AT = "2026-08-24T05:17:00Z"


def _write_profile(root: Path) -> Path:
    profile = root / "profile.yml"
    dump_yaml(
        profile,
        {
            "schema_version": "1.0",
            "project": {
                "id": PROJECT_ID,
                "name": "PIE AUTO-3 Controlled Outcome Calibration",
                "type": "calibration",
                "repository_root": ".",
                "baseline_branch": "main",
            },
            "technology": {"languages": ["python"]},
            "scope": {"include": ["src/**"], "exclude": []},
            "protected_paths": [],
            "review": {"packs": ["universal.architecture"]},
            "gate": {
                "block_on": ["P0"],
                "require": {"baseline_tests": False, "regression_tests": False},
            },
            "constraints": {
                "production_changes_allowed": False,
                "hosted_database_changes_allowed": False,
                "external_network_allowed": False,
            },
        },
    )
    return profile


def _write_evaluation(root: Path, source_revision: str) -> Path:
    target = root / CHANGED_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("VALUE = 1\n", encoding="utf-8")
    graph = {
        "schema_version": "1.0",
        "repository": {"root": "."},
        "nodes": [
            {
                "id": f"file:{CHANGED_PATH}",
                "type": "file",
                "path": CHANGED_PATH,
                "language": "python",
                "size_bytes": target.stat().st_size,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
        ],
        "edges": [],
        "stats": {
            "files": 1,
            "symbols": 0,
            "components": 0,
            "database_objects": 0,
            "edges": 0,
        },
        "warnings": [],
    }
    graph["graph_sha256"] = calculate_graph_sha256(graph)
    graph_path = root / "graph.json"
    dump_json(graph_path, graph)
    changed = root / "changed.txt"
    changed.write_text(CHANGED_PATH + "\n", encoding="utf-8")

    rules = {"schema_version": "1.0", "rules": []}
    baseline = root / "baseline.yml"
    challenger = root / "challenger.yml"
    dump_yaml(baseline, rules)
    dump_yaml(challenger, rules)

    cases = []
    for split in ("development", "validation", "holdout"):
        cases.append(
            {
                "case_id": f"auto3-{split}",
                "repository": REPOSITORY,
                "source_revision": source_revision,
                "input_artifacts": {
                    "graph": graph_path.name,
                    "changed_files": changed.name,
                },
                "configured_packs": [],
                "expected_changed_scope": [CHANGED_PATH],
                "expected_packs": [],
                "expected_tests": [],
                "expected_protected_result": "PASS",
                "labels": ["synthetic", "auto3-calibration-only"],
                "provenance": {
                    "source": "synthetic-auto3-calibration",
                    "labeled_by": ACTOR,
                    "labeled_at": CREATED_AT,
                },
                "split": split,
            }
        )
    dataset = root / "dataset.yml"
    dump_yaml(dataset, {"schema_version": "1.0", "dataset_id": "auto3-controlled-v1", "cases": cases})
    report = run_evaluation(dataset, baseline, challenger)
    if report["gate"]["decision"] != "PASS":
        raise RuntimeError(f"synthetic evaluation gate failed: {report['gate']}")
    if report["repeatability"] != {"runs": 2, "baseline": True, "challenger": True}:
        raise RuntimeError(f"synthetic evaluation is not repeatable: {report['repeatability']}")
    if report["comparison"]["protected_negative_regressions"]:
        raise RuntimeError("synthetic evaluation has protected-negative regressions")
    matching_holdout = [
        case for case in report["cases"]
        if case["source_revision"] == source_revision and case["split"] == "holdout"
    ]
    if len(matching_holdout) != 1:
        raise RuntimeError("synthetic evaluation does not have exactly one bound holdout case")
    path = root / "evaluation-report.json"
    write_evaluation_report(path, report)
    return path


def _source(head: str, base: str, pr_number: int) -> dict:
    value = {
        "schema_version": "1.0",
        "source": "github-cli",
        "retrieved_at": "2026-08-24T05:11:00Z",
        "repository": {
            "hostname": "github.com",
            "name_with_owner": REPOSITORY,
            "gh_repo_argument": REPOSITORY,
        },
        "pull_request": {
            "number": pr_number,
            "url": f"https://github.com/{REPOSITORY}/pull/{pr_number}",
            "title": "AUTO-3 controlled Outcome calibration",
            "body": "Synthetic-only calibration source projection.",
            "state": "OPEN",
            "is_draft": True,
            "is_cross_repository": False,
            "author": {"login": "gycha0109-beep"},
            "base_ref": "main",
            "base_oid": base,
            "head_ref": "calibration/auto3-controlled-outcome-20260824",
            "head_oid": head,
            "created_at": CREATED_AT,
            "updated_at": "2026-08-24T05:11:00Z",
            "merged_at": None,
            "merged_by": None,
            "mergeable": "MERGEABLE",
            "merge_state_status": "CLEAN",
            "review_decision": None,
            "additions": 1,
            "deletions": 0,
            "changed_files": [{"path": CHANGED_PATH, "additions": 1, "deletions": 0}],
            "commits": [],
            "labels": ["synthetic-calibration"],
            "reviews": [],
            "latest_reviews": [],
            "review_requests": [],
            "comments": [],
            "inline_review_comments": [],
            "checks": [],
        },
        "diff": {"requested": False, "available": False},
        "discussion": {"requested": False, "complete": True},
        "warnings": ["SYNTHETIC_AUTO3_CALIBRATION_SOURCE"],
        "local_repository_verification": {
            "status": "matched",
            "expected_repository": REPOSITORY,
            "expected_hostname": "github.com",
            "local_repository": {
                "name_with_owner": REPOSITORY,
                "hostname": "github.com",
                "url": f"https://github.com/{REPOSITORY}",
            },
        },
        "local_project_state": {
            "root": ".",
            "branch": "calibration/auto3-controlled-outcome-20260824",
            "head_revision": head,
            "baseline_revision": base,
            "working_tree_dirty": False,
            "working_tree_entries": [],
        },
    }
    refresh_source_hash(value)
    return value


def _write_request(root: Path, candidate: dict, source_revision: str) -> Path:
    request = root / "trust-request.json"
    dump_json(
        request,
        {
            "schema_version": "1.0",
            "task_id": candidate["task_id"],
            "source_revision": source_revision,
            "task_class": "formatting",
            "changed_files": candidate["changed_files"],
            "required_scenarios": [],
            "completed_scenarios": [],
            "repository_match": True,
            "head_match": True,
            "rollback_evidence": True,
            "replay_evidence": True,
            "readiness_policy": {
                "policy_id": "auto3-controlled-calibration",
                "policy_version": "1.0.0",
                "min_ledger_runs": 1,
                "min_ledger_decisions": 1,
                "min_defects": 1,
                "min_closed_defects": 0,
                "min_reground_observations": 1,
                "min_reground_coverage": 1.0,
                "min_reground_precision": 1.0,
                "min_reground_recall": 1.0,
                "max_reground_false_positive_rate": 0.0,
                "require_active_policy": True,
                "require_pass_evaluation": True,
                "require_holdout": True,
                "require_repeatability": True,
                "require_zero_protected_negative_regressions": True,
            },
        },
    )
    return request


def _init_campaign(root: Path) -> Path:
    workspace = root / "campaign"
    workspace.mkdir()
    write_registry(
        workspace / "comparison-registry.json",
        new_registry(PROJECT_ID, created_at="2026-08-24T05:12:00Z"),
    )
    dump_json(
        workspace / "reconciliation-sources.json",
        {
            "schema_version": "1.0",
            "project_id": PROJECT_ID,
            "assessment_sources": [],
            "outcome_sources": [],
        },
    )
    dump_json(
        workspace / "observation-policy.json",
        {
            "schema_version": "1.0",
            "policy_version": "1.0.0",
            "mode": "REPORT_ONLY",
            "target_band": "R0",
            "thresholds": {
                "minimum_r0_assessment_count": 20,
                "minimum_r0_reviewed_count": 20,
                "minimum_r0_conclusive_outcome_count": 12,
                "minimum_r0_confirmed_safe_count": 12,
                "minimum_confirmed_unsafe_challenge_count": 8,
                "minimum_r0_independent_audit_count": 5,
                "minimum_r0_outcome_coverage": 0.6,
                "minimum_r0_evidence_span_days": 14,
                "maximum_r0_false_negatives": 0,
                "maximum_r0_false_negative_rate": 0.0,
            },
        },
    )
    return workspace


def run(*, head: str, base: str, pr_number: int, output: Path) -> dict:
    if len(head) != 40 or len(base) != 40:
        raise RuntimeError("AUTO-3C requires exact 40-character Git SHAs")
    source_revision = "git:" + head.lower()
    output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="pie-auto3c-") as temporary:
        root = Path(temporary)
        profile = _write_profile(root)
        evaluation_path = _write_evaluation(root, source_revision)
        _, evaluation = load_evaluation_report(evaluation_path)

        source = _source(head.lower(), base.lower(), pr_number)
        candidate = build_github_prospective_capture_candidate(
            source,
            profile,
            generated_at="2026-08-24T05:11:30Z",
        )
        candidate_path = write_github_prospective_capture_candidate(root / "candidate.json", candidate)
        request = _write_request(root, candidate, source_revision)

        report = assess_trust(
            request,
            profile,
            evaluation_report=evaluation_path,
            generated_at="2026-08-24T05:13:00Z",
        )
        trust_report = root / "trust-report.json"
        write_trust_report(trust_report, report)
        policy_evidence = report.get("evidence", {}).get("policy", {})
        if policy_evidence.get("evaluation_available") is not True:
            raise RuntimeError("Trust report did not preserve evaluation authority")
        if policy_evidence.get("evaluation_id") != evaluation["evaluation_id"]:
            raise RuntimeError("Trust/evaluation id mismatch before campaign intake")
        if policy_evidence.get("evaluation_report_sha256") != evaluation["report_sha256"]:
            raise RuntimeError("Trust/evaluation report hash mismatch before campaign intake")

        workspace = _init_campaign(root)
        intake = intake_prospective_case(
            workspace,
            trust_report=trust_report,
            request=request,
            profile=profile,
            evaluation_report=evaluation_path,
            captured_at=CAPTURE_AT,
        )

        packet = prepare_review_packet(
            workspace,
            assessment_id=intake["assessment_id"],
            github_candidate=candidate_path,
            repository_root=root,
            github_cli=object(),
            generated_at=PACKET_AT,
            collect_pr=lambda *args, **kwargs: (deepcopy(source), None),
        )
        packet_path = write_review_packet(root / "review-packet.json", packet)
        submit_review_packet(
            packet_path,
            workspace_root=workspace,
            github_candidate=candidate_path,
            repository_root=root,
            github_cli=object(),
            review_level="REVIEWED",
            decision="APPROVE",
            actor=ACTOR,
            occurred_at=REVIEW_AT,
            confirmed_risk_band=report["risk"]["effective_band"],
            reason_codes=["SYNTHETIC_AUTO3_CALIBRATION_ONLY"],
            collect_pr=lambda *args, **kwargs: (deepcopy(source), None),
        )

        _, registry = load_registry(workspace / "comparison-registry.json")
        review_event = registry["events"][-1]
        if review_event["event_type"] != "HUMAN_DECISION":
            raise RuntimeError("synthetic governed review event was not recorded")

        declaration = build_outcome_declaration(
            actor=ACTOR,
            project_id=PROJECT_ID,
            assessment_id=intake["assessment_id"],
            source_revision=source_revision,
            trust_report_id=report["report_id"],
            trust_report_sha256=report["report_sha256"],
            review_event_id=review_event["event_id"],
            review_event_sha256=review_event["event_sha256"],
            review_level="REVIEWED",
            decision="APPROVE",
            review_packet_id=packet["packet_id"],
            review_packet_sha256=packet["packet_sha256"],
            authority_type="CONTROLLED_EVALUATION",
            verdict="SAFE",
            declared_at=DECLARED_AT,
            evidence_refs=[evaluation["evaluation_id"], evaluation["report_sha256"]],
            evaluation_id=evaluation["evaluation_id"],
            evaluation_report_sha256=evaluation["report_sha256"],
        )
        declaration_path = root / "outcome-declaration.json"
        declaration_path.write_text(
            json.dumps(declaration, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        first = transport_declared_outcome(
            workspace,
            declaration=declaration_path,
            evaluation_report=evaluation_path,
        )
        second = transport_declared_outcome(
            workspace,
            declaration=declaration_path,
            evaluation_report=evaluation_path,
        )
        if first["status"] != "DECLARED_OUTCOME_RECORDED_AND_RECONCILED":
            raise RuntimeError(f"AUTO-3B first transport did not reconcile: {first}")
        if first["reconciliation_status"] != "RECONCILED" or first["idempotent"]:
            raise RuntimeError(f"AUTO-3B first transport semantics invalid: {first}")
        if second["reconciliation_status"] != "RECONCILED" or not second["idempotent"]:
            raise RuntimeError(f"AUTO-3B replay was not idempotent: {second}")
        if first["event_id"] != second["event_id"]:
            raise RuntimeError("AUTO-3B replay changed Outcome event identity")
        if first["registry_sha256"] != second["registry_sha256"]:
            raise RuntimeError("AUTO-3B replay changed final campaign registry identity")
        if first["authority_key"] != second["authority_key"]:
            raise RuntimeError("AUTO-3B replay changed reconciled authority identity")

        _, final_registry = load_registry(workspace / "comparison-registry.json")
        outcomes = [event for event in final_registry["events"] if event["event_type"] == "OUTCOME"]
        if len(outcomes) != 1:
            raise RuntimeError(f"expected exactly one Outcome event, found {len(outcomes)}")
        progress = campaign_progress(workspace, generated_at="2026-08-24T05:18:00Z")

        summary = {
            "schema_version": "1.0",
            "calibration_contract": "PIE_AUTO3_CONTROLLED_OUTCOME_CALIBRATION_V1",
            "status": "AUTO3_CONTROLLED_CALIBRATION_PASS",
            "calibration_only": True,
            "synthetic_evidence": True,
            "synthetic_review_actor": ACTOR,
            "eligible_for_pilot_evidence": False,
            "repository": REPOSITORY,
            "pull_request": pr_number,
            "source_revision": source_revision,
            "base_revision": "git:" + base.lower(),
            "assessment_id": intake["assessment_id"],
            "trust_report_id": report["report_id"],
            "trust_report_sha256": report["report_sha256"],
            "predicted_risk_band": report["risk"]["effective_band"],
            "trust_readiness": report["readiness"]["status"],
            "review_event_id": review_event["event_id"],
            "review_packet_id": packet["packet_id"],
            "review_packet_sha256": packet["packet_sha256"],
            "evaluation_id": evaluation["evaluation_id"],
            "evaluation_report_sha256": evaluation["report_sha256"],
            "evaluation_gate": evaluation["gate"]["decision"],
            "declaration_id": declaration["declaration_id"],
            "declaration_sha256": declaration["declaration_sha256"],
            "first_transport": first,
            "replay_transport": second,
            "outcome_event_count": len(outcomes),
            "final_registry_sha256": final_registry["registry_sha256"],
            "campaign_status": progress["status"],
            "human_outcome_declared": True,
            "automatic_outcome_inference": False,
            "automation_authorized": False,
            "pilot_authorized": False,
            "merge_authorized": False,
            "deploy_authorized": False,
            "production_effect_authorized": False,
        }
        summary["summary_sha256"] = canonical_json_sha256(summary)

        dump_json(output / "summary.json", summary)
        dump_json(output / "transport-first.json", first)
        dump_json(output / "transport-replay.json", second)
        shutil.copy2(evaluation_path, output / "evaluation-report.json")
        shutil.copy2(trust_report, output / "trust-report.json")
        shutil.copy2(packet_path, output / "review-packet.json")
        shutil.copy2(declaration_path, output / "outcome-declaration.json")
        shutil.copy2(workspace / "comparison-registry.json", output / "comparison-registry.json")
        shutil.copy2(workspace / "reconciliation-sources.json", output / "reconciliation-sources.json")
        return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--head", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--pr-number", required=True, type=int)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    summary = run(
        head=args.head,
        base=args.base,
        pr_number=args.pr_number,
        output=Path(args.output).resolve(),
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())