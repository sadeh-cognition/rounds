"""Slack CLI entrypoint for the Django Slack analytics assistant."""

from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    os.chdir(REPO_ROOT)
    os.execvp("uv", ["uv", "run", "manage.py", "run_slack_assistant"])


if __name__ == "__main__":
    main()
