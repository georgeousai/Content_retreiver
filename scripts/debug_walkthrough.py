"""Step-through walkthrough of the real save_reel/ask pipeline for learning
purposes. Not part of the app, not a test — a debugger target.

Uses the exact same adapters the bot does, by calling the same
`reel_vault.main.build_vault` the bot calls, just driven from a prompt instead
of a Telegram chat. So you can set breakpoints and step through without a live
chat round-trip, and against whichever provider `.env` currently names — this
script knows about none of them.

Sharing that one builder is deliberate. This file used to wire its own copy of
the adapter list, and drifted so far from the real one that it constructed a
`Groq` client, imported an `adapters.groq_llm` module and read a
`config.groq_api_key` — all three gone for months, none of it noticed, because
a duplicate of the wiring is never run alongside the wiring it duplicates.

Run this under the VS Code debugger (see .vscode/launch.json), not with
`uv run` directly, or you'll just see it finish with no chance to inspect
anything.
"""

from __future__ import annotations

import logging

from reel_vault.config import load_config
from reel_vault.main import build_vault


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = load_config()

    # --- Step 1: build the vault -------------------------------------------
    # Breakpoint here, then Step Into (F11) to watch each real adapter get
    # constructed — the same ones `main()` hands to the bot.
    vault = build_vault(config)

    # --- Step 2: save a reel -------------------------------------------------
    url = input("Paste an Instagram Reel URL to save (or press Enter to skip): ").strip()
    if url:
        # Breakpoint here, then Step Into (F11) to follow save_reel() itself.
        result = vault.save_reel(url)
        print(f"\nsave_reel result: {type(result).__name__}")
        print(result)

    # --- Step 3: ask a question ----------------------------------------------
    query = input("\nAsk a question about your saved reels (or press Enter to skip): ").strip()
    if query:
        # Breakpoint here, then Step Into (F11) to follow ask() itself.
        answer = vault.ask(query)
        print(f"\nask result: {type(answer).__name__}")
        print(answer)

    # The video pipeline is not run here. It is the bot's background worker
    # that reads a reel's video, and a save from this script leaves the reel
    # PENDING for the next real run to pick up — which is the resume path
    # working, not a gap in this script.


if __name__ == "__main__":
    main()
