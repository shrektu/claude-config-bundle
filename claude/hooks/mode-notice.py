#!/usr/bin/env python3
import os
import sys

MODE_VAR = "CLAUDE_MODE"
PERSONAL_MODE = "personal"
NOTICE = (
    "mode: personal (CLAUDE_MODE=personal) - Codex off: final review = "
    "reviewer-opus + flash-review-runner (S: flash-review-runner alone; "
    "Flash unavailable -> reviewer-opus), plan gate without Codex fallback; "
    "no redakcja, company style guide, glossary or `terms` checks "
    "(writer and ui-writer proofread themselves); "
    "no AI footer on published text."
)


def main() -> int:
    """Print the personal-mode notice, or nothing in work mode."""
    try:
        if os.environ.get(MODE_VAR, "").strip().lower() == PERSONAL_MODE:
            print(NOTICE)
    except OSError:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
