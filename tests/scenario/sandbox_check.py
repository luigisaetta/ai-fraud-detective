"""
Author: L. Saetta
Date Last Modified: 2026-11-23
License: MIT
Description: Runs the reference solver on the sample bundle in a real OCI
    sandbox, and checks that the result is the same as on the local machine.

    It confirms that standard-library code like the agent's runs on the
    sandbox runtime (Python 3.11, no third-party packages, no network), and
    that the hash of the uploaded bundle matches the reference hash.

    It creates a sandbox, so it takes minutes and is not part of the test
    suite. The sandbox is deleted at the end.

Usage:

    python -m tests.scenario.sandbox_check
"""

import hashlib
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path

from tests.scenario import reference_solver
from triage.config import Settings
from triage.ingest import BUNDLE_DIR, BundleUploader
from triage.oci_clients import OciClients
from triage.sample_case.case import SampleCase
from triage.sandbox import SandboxManager

#: Where the solver and a copy of the zip go in the sandbox.
WORK_DIR = "/workspace/check"

#: Seconds allowed for each command in the sandbox.
TIMEOUT_SECONDS = 120


def expected_result(archive: bytes) -> dict:
    """The solver result on the local machine, on our own generated bundle."""
    with tempfile.TemporaryDirectory() as folder:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            bundle.extractall(folder)
        return reference_solver.solve(Path(folder))


def main() -> int:
    """Run the check and print the outcome.

    Returns:
        0 when the sandbox gives the expected result, 1 otherwise.
    """
    archive = SampleCase().archive()
    digest = hashlib.sha256(archive).hexdigest()
    expected = expected_result(archive)
    settings = Settings.load()
    manager = SandboxManager.from_settings(settings, OciClients(settings))
    with tempfile.TemporaryDirectory() as folder:
        local = Path(folder) / "halden-ap-q3-2026.zip"
        local.write_bytes(archive)
        print("Creating a sandbox (this can take minutes)...", flush=True)
        with manager.create(
            on_progress=lambda text: print(f"  {text}", flush=True)
        ) as session:
            print(BundleUploader(session).upload(local).describe())
            session.run(f"mkdir -p {WORK_DIR}", timeout_seconds=TIMEOUT_SECONDS)
            session.write_file(f"{WORK_DIR}/bundle.zip", archive)
            solver = Path(reference_solver.__file__).read_text(encoding="utf-8")
            session.write_file(f"{WORK_DIR}/reference_solver.py", solver)
            version = session.run("python3 -V", timeout_seconds=TIMEOUT_SECONDS)
            remote_hash = session.run(
                f"sha256sum {WORK_DIR}/bundle.zip", timeout_seconds=TIMEOUT_SECONDS
            )
            result = session.run(
                f"python3 -I {WORK_DIR}/reference_solver.py {BUNDLE_DIR}",
                timeout_seconds=TIMEOUT_SECONDS,
            )
    print(f"Sandbox runtime: {version.output.strip()}")
    hash_ok = remote_hash.output.split()[:1] == [digest]
    print(f"Hash in the sandbox matches the reference: {hash_ok}")
    if not result.ok:
        print(f"Solver failed (exit {result.exit_code}):\n{result.output[-2000:]}")
        return 1
    same = json.loads(result.output) == expected
    print(f"Solver result in the sandbox equals the local one: {same}")
    print(json.dumps(json.loads(result.output), indent=2)[:3000])
    return 0 if hash_ok and same else 1


if __name__ == "__main__":
    sys.exit(main())
