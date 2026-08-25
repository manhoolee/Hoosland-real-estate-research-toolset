#!/usr/bin/env python3
"""Smoke-test the real-estate DeepSeek Harness runtime configuration."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from deepseek_harness import DeepSeekHarness
from deepseek_harness.models import Notification


def report(notification: Notification) -> None:
    """Print event names without leaking message or tool payloads."""
    if notification.method == "session.event":
        event = notification.payload.get("event")
        if isinstance(event, dict) and isinstance(event.get("type"), str):
            print(f"event: {event['type']}", flush=True)
    elif notification.method == "session.status":
        print(f"status: {notification.payload.get('status')}", flush=True)


def main() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    config = Path(os.environ.get("DSH_CONFIG", repository_root / "backend" / "cordis.yml"))
    workspace = Path(os.environ.get("DSH_CWD", repository_root / ".runtime-probe" / "workspace"))
    session_root = Path(os.environ.get("DSH_SESSION_ROOT", repository_root / ".runtime-probe" / "sessions"))
    prompt = " ".join(sys.argv[1:]) or (
        "请使用 comprehensive-real-estate-expert，"
        "请只回复：房地产专家运行时已就绪。不要调用外部工具。"
    )

    workspace.mkdir(parents=True, exist_ok=True)
    session_root.mkdir(parents=True, exist_ok=True)
    for directory in ("inputs", "work", "outputs"):
        (workspace / directory).mkdir(exist_ok=True)

    with DeepSeekHarness(
        provider="deepseek-official",
        model=os.environ.get("DSH_MODEL", "deepseek-v4-flash"),
        max_tokens=int(os.environ.get("DSH_MAX_TOKENS", "8192")),
        cwd=str(workspace.resolve()),
        session_root=str(session_root.resolve()),
        cordis=str(config.resolve()),
    ) as harness:
        result = harness.run(prompt, session_id="runtime-probe", on_notification=report)
    print(result.final_response)


if __name__ == "__main__":
    main()
