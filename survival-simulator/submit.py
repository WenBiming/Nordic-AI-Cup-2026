"""Talk to the Nordic AI Cup platform API for the survival-simulator use case.

    export NAC_TOKEN=<your team api key>          # sent as the x-token header
    python submit.py verify   [--url http://135.225.108.128]   # platform sends one sample to your endpoint
    python submit.py status                                    # team, past attempts and scores
    python submit.py validate [--url ...] [--wait]             # enqueue a validation attempt (unlimited)
    python submit.py evaluate [--url ...] [--wait] --yes       # enqueue THE evaluation attempt (one per team)
    python submit.py poll <queued_attempt_uuid> [--kind validate|evaluate]

API: https://cases.nordicaicup.com/api/docs
"""
import argparse
import json
import os
import sys
import time

import requests

BASE = "https://cases.nordicaicup.com/api/v1/usecases/survival-simulator"
DEFAULT_URL = "http://135.225.108.128"


def call(method, path, token=None, body=None):
    headers = {"x-token": token} if token else {}
    r = requests.request(method, BASE + path, headers=headers, json=body, timeout=60)
    try:
        data = r.json()
    except ValueError:
        data = r.text
    if r.status_code >= 400:
        sys.exit(f"{method} {path} -> HTTP {r.status_code}: {json.dumps(data, indent=2)}")
    return data


def poll(kind, uuid, token, every=30):
    """Print queue state until the attempt has a result, then print it."""
    while True:
        queued = call("GET", f"/{kind}/queue/{uuid}", token)
        attempt = call("GET", f"/{kind}/queue/{uuid}/attempt", token)
        status = queued.get("status") if isinstance(queued, dict) else queued
        pos = queued.get("position_in_queue") if isinstance(queued, dict) else None
        if isinstance(attempt, dict) and attempt.get("finished_at"):
            print(json.dumps(attempt, indent=2))
            return attempt
        print(f"{time.strftime('%H:%M:%S')} status={status} position={pos}")
        time.sleep(every)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["verify", "status", "validate", "evaluate", "poll"])
    p.add_argument("uuid", nargs="?")
    p.add_argument("--url", default=DEFAULT_URL, help="your endpoint base URL (the platform posts to /predict)")
    p.add_argument("--kind", default="validate", choices=["validate", "evaluate"], help="for poll")
    p.add_argument("--wait", action="store_true", help="poll until the attempt finishes")
    p.add_argument("--yes", action="store_true", help="required for evaluate (one attempt per team)")
    p.add_argument("--token", default=os.environ.get("NAC_TOKEN"))
    a = p.parse_args()
    if not a.token:
        sys.exit("set NAC_TOKEN or pass --token")

    if a.command == "verify":
        print(json.dumps(call("POST", "/verify", a.token, {"url": a.url}), indent=2))
    elif a.command == "status":
        print(json.dumps(call("GET", "/status", a.token), indent=2))
    elif a.command in ("validate", "evaluate"):
        if a.command == "evaluate" and not a.yes:
            sys.exit("evaluation is a single attempt per team: re-run with --yes")
        res = call("POST", f"/{a.command}/queue", a.token, {"url": a.url})
        print(json.dumps(res, indent=2))
        if a.wait:
            poll(a.command, res["queued_attempt_uuid"], a.token)
    elif a.command == "poll":
        if not a.uuid:
            sys.exit("poll needs the queued_attempt_uuid")
        poll(a.kind, a.uuid, a.token)


if __name__ == "__main__":
    main()
