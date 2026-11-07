from collections.abc import Iterable


def assert_no_mismatches(mismatch_messages: Iterable[str], *, failure_claim: str) -> None:
    """Fails once with every mismatch and how many there were, so one run shows all that is wrong."""
    collected_mismatch_messages: list[str] = list(mismatch_messages)
    failure_report: str = "\n".join(collected_mismatch_messages)
    assert not failure_report, f"{failure_claim}; {len(collected_mismatch_messages)} mismatches:\n{failure_report}"
