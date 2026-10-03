"""THROWAWAY — DEP-2 gate proof: must fail CI, then be reverted."""


def test_ci_gate_proof_fails():
    assert False, "DEP-2 gate proof: this failure is intentional"
