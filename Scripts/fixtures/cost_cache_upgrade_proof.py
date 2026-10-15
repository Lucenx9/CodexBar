#!/usr/bin/env python3
"""Exercise a released 0.76.0 cache upgrade through the public cost CLI."""

import argparse
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile


def digest(value):
    return hashlib.sha256(value).hexdigest()


def database_snapshot(path):
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        snapshot = {}
        for table in tables:
            rows = connection.execute(f'SELECT * FROM "{table}"').fetchall()
            snapshot[table] = sorted(rows, key=repr)
        parser_hash = connection.execute(
            "SELECT value FROM meta WHERE key = 'parser_hash'").fetchone()[0]
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        connection.row_factory = sqlite3.Row
        files = [dict(row) for row in connection.execute("SELECT * FROM files")]
    return snapshot, parser_hash, version, files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    baseline = args.baseline.resolve(strict=True)
    candidate = args.candidate.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="cost-cache-upgrade-") as temporary:
        root = Path(temporary)
        sessions = root / ".codex" / "sessions"
        pi = root / "pi"
        sessions.mkdir(parents=True)
        pi.mkdir()
        environment = {
            "PATH": os.defpath, "HOME": str(root), "TZ": "UTC",
            "CODEX_HOME": str(root / ".codex"),
            "XDG_CACHE_HOME": str(root / "cache"),
            "CODEXBAR_CONFIG": str(root / "config.json"),
            "PI_CODING_AGENT_SESSION_DIR": str(pi),
        }

        def invoke(binary, arguments):
            result = subprocess.run([str(binary), *arguments], env=environment, cwd=root,
                                    capture_output=True, check=True, timeout=60)
            return result.stdout

        def cost(binary, refresh=False):
            arguments = ["cost", "--provider", "codex", "--days", "1", "--json"]
            if refresh:
                arguments.append("--refresh")
            return json.loads(invoke(binary, arguments))

        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

        def native_record(response, input_tokens, output_tokens, total_input, total_output):
            return {"type": "token_usage_record", "timestamp": timestamp, "payload": {
                "thread_id": "fixture-native", "response_id": response, "model": "gpt-5",
                "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
                "thread_token_usage": {"input_tokens": total_input, "output_tokens": total_output},
            }}

        def pi_record(identifier, input_tokens, output_tokens):
            return {"type": "message", "id": identifier, "timestamp": timestamp, "message": {
                "role": "assistant", "provider": "openai-codex", "model": "gpt-5",
                "usage": {"input": input_tokens, "output": output_tokens,
                          "totalTokens": input_tokens + output_tokens, "cacheRead": 0, "cacheWrite": 0},
            }}

        def append(path, record):
            with path.open("a") as output:
                output.write(json.dumps(record) + "\n")

        native = sessions / "native.jsonl"
        append(native, {"type": "session_meta", "payload": {"id": "fixture-native", "cwd": "/synthetic"}})
        append(native, native_record("fixture-response-1", 100, 10, 100, 10))
        pi_file = pi / "fixture.jsonl"
        append(pi_file, pi_record("fixture-pi-1", 40, 10))
        version = invoke(baseline, ["--version"]).decode().strip()
        assert version == "CodexBar 0.76.0", version
        invoke(baseline, ["config", "disable", "--provider", "claude", "--json"])
        assert cost(baseline)[0]["last30DaysTokens"] == 160

        # Exceed the shipped 256 MiB per-file scan budget by 1 MiB. The old CLI
        # must save an unfinished JSONL checkpoint and retain the existing report.
        large = sessions / "large.jsonl"
        with large.open("wb") as output:
            output.write(json.dumps({"type": "session_meta", "payload": {"id": "fixture-large"}}).encode() + b"\n")
            output.write(b'{"type":"response_item","payload":{"text":"')
            block = b"x" * (1024 * 1024)
            for _ in range(257):
                output.write(block)
            output.write(b'"}}\n')
        before_report = cost(baseline, refresh=True)
        database = next(root.rglob("cost-usage.sqlite"))
        pi_cache = next(root.rglob("pi-sessions-v9.json"))
        before, old_hash, old_version, old_files = database_snapshot(database)
        database_inode = database.stat().st_ino
        checkpoint = next(row for row in old_files if row["path"] == str(large))
        resume = json.loads(checkpoint["scan_state"])["resumePayload"]
        assert old_hash == "3f88178bf03ad704" and checkpoint["scan_complete"] == 0
        assert checkpoint["parsed_bytes"] == 256 * 1024 * 1024 and resume
        stored_report = json.loads(before["scan_metadata"][0][1])["previousReportPayload"]
        assert stored_report and len(before["usage_rows"]) == 1
        before_pi = json.loads(pi_cache.read_text())
        settings_bytes = (root / "config.json").read_bytes()
        settings = json.loads(invoke(baseline, ["config", "dump", "--json"]))

        after_report = cost(candidate)
        after, new_hash, new_version, _ = database_snapshot(database)
        after_pi = json.loads(pi_cache.read_text())
        assert new_hash == "b952c48950b82f8f" and new_version != old_version
        assert database.stat().st_ino == database_inode
        preserved = [table for table in before if table != "meta"]
        assert all(before[table] == after[table] for table in preserved)
        assert before_pi["pricingKey"] != after_pi["pricingKey"]
        assert before_pi["files"] == after_pi["files"]
        assert before_pi["daysByProvider"] == after_pi["daysByProvider"]
        assert before_pi["sessionRootsFingerprint"] == after_pi["sessionRootsFingerprint"]
        assert before_pi["lastScanUnixMs"] < after_pi["lastScanUnixMs"]
        assert (root / "config.json").read_bytes() == settings_bytes
        assert json.loads(invoke(candidate, ["config", "dump", "--json"])) == settings
        for report in [before_report, after_report]:
            report[0].pop("updatedAt", None)
        assert before_report == after_report and after_report[0]["last30DaysTokens"] == 160

        append(native, native_record("fixture-response-2", 50, 5, 150, 15))
        append(pi_file, pi_record("fixture-pi-2", 30, 5))
        refreshed_report = cost(candidate, refresh=True)
        refreshed, _, _, refreshed_files = database_snapshot(database)
        completed = next(row for row in refreshed_files if row["path"] == str(large))
        assert completed["scan_complete"] == 1 and completed["parsed_bytes"] == large.stat().st_size, (
            completed["parsed_bytes"], completed["scan_complete"], large.stat().st_size,
            refreshed_report[0]["last30DaysTokens"])
        assert not json.loads(completed["scan_state"]).get("resumePayload")
        assert len(refreshed["usage_rows"]) == 2
        assert refreshed_report[0]["last30DaysTokens"] == 250
        refreshed_pi = json.loads(pi_cache.read_text())
        pi_tokens = sum(usage["totalTokens"] for day in refreshed_pi["daysByProvider"]["codex"].values()
                        for usage in day.values())
        assert pi_tokens == 85
        assert (root / "config.json").read_bytes() == settings_bytes

        print(json.dumps({
            "baselineVersion": version,
            "baselineBinarySHA256": digest(baseline.read_bytes()),
            "candidateBinarySHA256": digest(candidate.read_bytes()),
            "parserHashBefore": old_hash, "parserHashAfter": new_hash,
            "userVersionBefore": old_version, "userVersionAfter": new_version,
            "nativeDatabaseFileRetained": True,
            "nativeTablesByteForBytePreservedAtAdoption": {table: len(before[table]) for table in preserved},
            "retainedReportSHA256": digest(base64.b64decode(stored_report)),
            "checkpointBytesPreservedAtAdoption": checkpoint["parsed_bytes"],
            "checkpointResumePayloadBytes": len(base64.b64decode(resume)),
            "checkpointResumedToEOFBytes": completed["parsed_bytes"],
            "settingsSHA256BeforeAndAfter": digest(settings_bytes),
            "settingsDumpUnchanged": True,
            "piPricingFingerprintChanged": True, "piRefreshTimestampAdvanced": True,
            "piCachedFilesAndContributionsPreservedAtAdoption": True,
            "tokensBeforeAndAfterAdoption": 160,
            "tokensAfterNativeAndPiAppend": 250,
            "piTokensAfterAppend": pi_tokens,
            "nativeUsageRowsBeforeAndAfterAppend": [1, 2],
            "fixture": "synthetic only; same HOME/cache/config across released and candidate CLIs",
            "reportComparisonIgnores": ["updatedAt"],
        }, indent=2))


if __name__ == "__main__":
    main()
