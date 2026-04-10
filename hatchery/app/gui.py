from pathlib import Path


def render_acceptance_console() -> str:
    return Path(__file__).with_name("gui.html").read_text(encoding="utf-8")


__all__ = ["render_acceptance_console"]
