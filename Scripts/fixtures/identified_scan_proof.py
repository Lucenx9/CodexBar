#!/usr/bin/env python3
"""Measure an identified scan using synthetic message text and one owned request."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--messages", type=int, default=5000)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    if args.messages < 0 or args.timeout <= 0:
        parser.error("messages must be nonnegative and timeout must be positive")
    binary = args.binary.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="identified-scan-proof-") as temporary:
        root = Path(temporary)
        sessions = root / ".codex" / "sessions"
        sessions.mkdir(parents=True)
        fixture = sessions / "synthetic.jsonl"
        message = json.dumps({
            "type": "response_item",
            "timestamp": "2026-08-31T12:00:00Z",
            "payload": {
                "type": "message",
                "content": [{"type": "input_text", "text": "synthetic text " * 1000}],
            },
        }, separators=(",", ":")) + "\n"
        usage = {"input_tokens": 100, "cached_input_tokens": 20, "output_tokens": 10}
        with fixture.open("w") as output:
            output.write(json.dumps({"type": "session_meta", "payload": {"id": "fixture-session"}}) + "\n")
            for _ in range(args.messages):
                output.write(message)
            output.write(json.dumps({
                "type": "token_usage_record",
                "timestamp": "2026-08-31T12:00:00Z",
                "payload": {
                    "thread_id": "fixture-session",
                    "response_id": "fixture-response",
                    "model": "gpt-5",
                    "usage": usage,
                    "thread_token_usage": usage,
                },
            }) + "\n")
        environment = {
            "PATH": os.defpath,
            "HOME": str(root),
            "CODEX_HOME": str(root / ".codex"),
            "XDG_CACHE_HOME": str(root / "cache"),
        }
        command = [str(binary), "cost", "--provider", "codex", "--identified-only", "--days", "1",
                   "--identified-end", "1788177600000", "--json"]
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        started = time.monotonic()
        result = subprocess.run(command, env=environment, capture_output=True, timeout=args.timeout, check=True)
        elapsed = time.monotonic() - started
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu = after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime
        ledger = json.loads(result.stdout)
        assert ledger["startUnixMs"] == 1788134400000 and ledger["endUnixMs"] == 1788177600000
        records = ledger["records"]
        tokens = sum(row["inputTokens"] + row["outputTokens"] for row in records)
        assert len(records) == 1 and tokens == 110
        assert not ledger["partial"] and ledger["excludedCount"] == 0 and not ledger["conflictingIDs"]
        print(json.dumps({
            "fixture": "synthetic response_item messages followed by one owned request",
            "messages": args.messages,
            "fixtureBytes": fixture.stat().st_size,
            "days": 1,
            "elapsedSeconds": round(elapsed, 3),
            "cpuSeconds": round(cpu, 3),
            "exitCode": result.returncode,
            "requests": len(records),
            "totalTokens": tokens,
            "partial": ledger["partial"],
            "ledgerSHA256": hashlib.sha256(json.dumps(ledger, sort_keys=True).encode()).hexdigest(),
        }, indent=2))


if __name__ == "__main__":
    main()
