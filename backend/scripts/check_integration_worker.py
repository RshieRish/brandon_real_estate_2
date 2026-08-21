"""Fail-closed post-deploy readiness check using the Python standard library."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request


EXPECTED_READY = {
    "status": "ready",
    "service": "integration-worker",
    "database": "ok",
    "migration": "ok",
    "heartbeat": "ok",
    "job_registry": "ok",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--timeout", required=True, type=float)
    arguments = parser.parse_args()
    if arguments.timeout <= 0:
        print("integration-worker not ready", file=sys.stderr)
        return 1
    ready_url = f"{arguments.base_url.rstrip('/')}/ready"
    try:
        with urllib.request.urlopen(
            ready_url,
            timeout=arguments.timeout,
        ) as response:
            if response.status != 200:
                raise RuntimeError("unexpected status")
            payload = json.loads(response.read().decode("utf-8"))
            if payload != EXPECTED_READY:
                raise RuntimeError("unexpected response")
    except Exception:
        print("integration-worker not ready", file=sys.stderr)
        return 1
    print("integration-worker ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
