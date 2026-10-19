from typing import NoReturn

UNAVAILABLE_PREFIX = "AGY-UNAVAILABLE: "


class AgyUnavailableError(Exception):
    """A failure reported to the caller as AGY-UNAVAILABLE."""

    def __init__(self, reason: str, details: str = "") -> None:
        """Store the reason and optional extra text."""
        super().__init__(reason)
        self.reason = reason
        self.details = details

    def render(self) -> str:
        """Return the text handed back to the MCP caller."""
        text = f"{UNAVAILABLE_PREFIX}{self.reason}"
        if self.details:
            text += f"\n\n{self.details}"
        return text


def fail(reason: str, details: str = "") -> NoReturn:
    """Abort the tool call with an AGY-UNAVAILABLE reply."""
    raise AgyUnavailableError(reason, details)
