"""Ensure Procrastinate queue tables exist (run in the migrate service)."""
from __future__ import annotations

from .jobs import ensure_open


def main() -> None:
    ensure_open()
    print("procrastinate schema migrated")


if __name__ == "__main__":
    main()
