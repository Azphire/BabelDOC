"""Meta-check for C01-C21 fast-gate registration and delivery evidence."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spec_checks.delivery_commits import DELIVERY_COMMITS  # noqa: E402
from spec_checks.delivery_commits import delivery_files  # noqa: E402
from spec_checks.delivery_commits import resolve_delivery_commit  # noqa: E402

GATE_SET = "fast"

DELIVERY_GATES = (
    "spec_check_magazine_runtime_profile.py",
    "spec_check_article_flow_ir.py",
    "spec_check_run_trace.py",
    "spec_check_fixed_asset_guard.py",
    "spec_check_chain_single_request.py",
    "spec_check_chain_slot_backfill.py",
    "spec_check_article_cross_column.py",
    "spec_check_article_cross_page.py",
    "spec_check_repair_transaction.py",
    "spec_check_reflow_compliance.py",
    "spec_check_drop_cap_intent.py",
    "spec_check_drop_cap_english.py",
    "spec_check_drop_cap_chinese.py",
    "spec_check_drop_cap_repair_guard.py",
    "spec_check_pdf_compliance.py",
)
C16_GATES = (
    "spec_check_startup_modes.py",
    "spec_check_cli_credentials.py",
    "spec_check_startup_distribution.py",
)
AUDIT_GATES = (
    "spec_check_debug_semantic_invariance.py",
    "spec_check_debug_overlay_render.py",
    "spec_check_geometry_write_guard.py",
    "spec_check_physical_page_identity.py",
    "spec_check_article_ir_contract.py",
    "spec_check_chain_owner_scope.py",
    "spec_check_article_state_checkpoints.py",
    "spec_check_repair_methodology_contract.py",
    "spec_check_repair_action_handlers.py",
    "spec_check_tool_call_transport.py",
    "spec_check_repair_tool_schema.py",
    "spec_check_hitl_source_binding.py",
    "spec_check_manual_constraint_delivery.py",
    "spec_check_targeted_page_compliance.py",
    "spec_check_manual_constraint_final.py",
    "spec_check_targeted_pdf_acceptance.py",
    "spec_check_evaluation_readiness.py",
    "spec_check_eval_labels.py",
)
SCOPE_GATES = {
    "C02": "spec_check_article_flow_ir.py",
    "C03": "spec_check_run_trace.py",
    "C06": "spec_check_chain_slot_backfill.py",
    "C07": "spec_check_article_cross_column.py",
    "C08": "spec_check_article_cross_page.py",
    "C10": "spec_check_reflow_compliance.py",
}
GATE_SET_PATTERN = re.compile(r'^GATE_SET\s*=\s*"([a-z]+)"', re.MULTILINE)


def registered_gates() -> tuple[str, ...]:
    tree = ast.parse((ROOT / "spec_checks" / "run_all.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "GATES" for target in node.targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
                return value
    raise AssertionError("spec_checks/run_all.py has no literal GATES tuple")


def main() -> int:
    registered = registered_gates()
    expected_gates = (*DELIVERY_GATES, *C16_GATES, *AUDIT_GATES)
    assert all(registered.count(gate) == 1 for gate in expected_gates)
    positions = [registered.index(gate) for gate in expected_gates]
    assert positions == sorted(positions)
    assert len(AUDIT_GATES) == 18
    assert registered.index("spec_check_gate_registration.py") > positions[-1]
    for gate in expected_gates:
        source = (ROOT / "spec_checks" / gate).read_text(encoding="utf-8")
        match = GATE_SET_PATTERN.search(source)
        assert match is not None and match.group(1) == "fast", gate
    assert tuple(DELIVERY_COMMITS) == tuple(f"C{index:02d}" for index in range(1, 16))
    for batch in DELIVERY_COMMITS:
        assert len(resolve_delivery_commit(batch, ROOT)) == 40
    for batch, gate in SCOPE_GATES.items():
        source = (ROOT / "spec_checks" / gate).read_text(encoding="utf-8")
        assert "batch-C" not in source
        assert '["git", "diff", "--name-only", "HEAD"]' not in source
        assert f'delivery_files("{batch}", ROOT)' in source
        assert f"spec_checks/{gate}" in delivery_files(batch, ROOT)
    print(
        "PASS: C01-C21 fast gates and C01-C15 delivery commits are registered"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
