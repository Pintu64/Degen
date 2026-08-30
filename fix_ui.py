#!/usr/bin/env python3
"""Validate Telegram UI source and callback payload limits."""

import ast
from pathlib import Path

from app.bot.keyboards import call_inline, home_inline, scan_inline, token_inline
from app.domain import Chain

ROOT = Path(__file__).resolve().parent


def _callback_values(markup):
    for row in markup.inline_keyboard:
        for button in row:
            if button.callback_data:
                yield button.callback_data


def main() -> None:
    for source in ("app/bot/formatting.py", "app/bot/handlers.py", "app/bot/keyboards.py"):
        path = ROOT / source
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    markups = [
        home_inline(),
        scan_inline(),
        call_inline(123),
        token_inline(Chain.ETHEREUM, "0x" + "a" * 40),
        token_inline(Chain.SOLANA, "So11111111111111111111111111111111111111112"),
    ]
    callbacks = [value for markup in markups for value in _callback_values(markup)]
    oversized = [value for value in callbacks if len(value.encode("utf-8")) > 64]
    if oversized:
        raise SystemExit(f"Oversized Telegram callback data: {oversized}")
    print(f"Telegram UI validation passed ({len(callbacks)} callbacks checked).")


if __name__ == "__main__":
    main()
