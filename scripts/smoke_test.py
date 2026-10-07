"""End-to-end smoke test against a running deployment.

    python scripts/smoke_test.py --base-url http://localhost:8000

Creates an API key, uploads two sample files, waits for processing and checks the results.
Used by CI against `docker compose`, and handy for checking a live deployment.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
EXPECTED = {
    "farm_survey.kml": {"feature_count": 8, "measured_count": 6},
    "pipelines_utm43n.zip": {"feature_count": 2, "measured_count": 2},
}


def wait_until(check, timeout: float, what: str):
    deadline = time.monotonic() + timeout
    while True:
        try:
            result = check()
            if result:
                return result
        except httpx.HTTPError:
            pass
        if time.monotonic() > deadline:
            sys.exit(f"FAIL: timed out waiting for {what}")
        time.sleep(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        wait_until(lambda: client.get("/health").status_code == 200, args.timeout, "/health")

        key = client.post("/api/auth/keys/", json={"name": "smoke test"})
        client.headers["X-API-Key"] = key.raise_for_status().json()["api_key"]

        for filename, expected in EXPECTED.items():
            with (SAMPLES / filename).open("rb") as stream:
                upload = client.post("/api/files/", files={"file": (filename, stream)})
            file_id = upload.raise_for_status().json()["id"]

            def finished(file_id: str = file_id) -> dict | None:
                info = client.get(f"/api/files/{file_id}/").raise_for_status().json()
                return info if info["status"] in ("COMPLETED", "FAILED") else None

            info = wait_until(finished, args.timeout, f"{filename} to be processed")
            if info["status"] != "COMPLETED":
                sys.exit(f"FAIL: {filename} failed: {info['error']}")

            measurements = client.get(f"/api/files/{file_id}/measurements/").raise_for_status()
            summary = measurements.json()["summary"]
            for field, value in expected.items():
                if summary[field] != value:
                    sys.exit(f"FAIL: {filename}: {field} is {summary[field]}, expected {value}")
            print(
                f"ok  {filename}: {summary['feature_count']} features, "
                f"area {summary['total_area_m2']} m2, length {summary['total_length_m']} m"
            )

        viewer = client.get("/")
        print(f"ok  viewer: HTTP {viewer.status_code}" if viewer.is_success else "--  no viewer")
    print("Smoke test passed.")


if __name__ == "__main__":
    main()
