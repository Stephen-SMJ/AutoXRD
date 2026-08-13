#!/usr/bin/env python3
"""Probe one OpenAI-compatible model without exposing its credential."""

from __future__ import annotations

import argparse
import json
import os
import time

from core.llm import LLMClient


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", choices=("low", "medium", "high"), default="high")
    args = parser.parse_args()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        parser.error("OPENAI_API_KEY is required")

    started = time.monotonic()
    client = LLMClient(provider="openai", api_key=api_key, base_url=args.base_url)
    stream = client.stream_messages(
        model=args.model,
        max_tokens=64,
        system="This is an API compatibility probe.",
        messages=[{"role": "user", "content": "Reply with exactly OK."}],
        tools=[],
        effort=args.effort,
    )
    with stream:
        text = "".join(stream.text_stream)
        final = stream.get_final_message()
    print(json.dumps({
        "ok": bool(text.strip() or final.content),
        "model": args.model,
        "elapsed_seconds": time.monotonic() - started,
        "response_preview": text.strip()[:80],
        "usage_reported": final.usage is not None,
        "stop_reason": final.stop_reason,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
