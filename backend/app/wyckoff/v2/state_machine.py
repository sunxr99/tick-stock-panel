"""Shared state-machine invariants for independent Wyckoff v2 event chains."""

TERMINAL_STATES = frozenset({
    "SPRING_CONFIRMED",
    "HARD_INVALIDATION",
    "TEST_TIMEOUT",
    "TEST_REJECTED",
    "NO_FOLLOW_THROUGH",
    "SOS_CONFIRMED",
    "SOS_FAILED",
    "LPS_CONFIRMED",
    "LPS_FAILED",
})


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES
