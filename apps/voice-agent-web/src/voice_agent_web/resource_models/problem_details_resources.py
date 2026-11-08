from typing import TypedDict


class ProblemDetailsResource(TypedDict):
    """An RFC 9457 problem details body."""

    type: str
    title: str
    status: int
    detail: str
    instance: str
