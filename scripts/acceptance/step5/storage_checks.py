"""Linux named-volume checks, invoked explicitly by run.py (no Windows fallback)."""

import copy
import json
import os
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from app.core.anonymous_session import AnonymousSessionStore, SessionError, bootstrap

DATA = Path("/storage-tests")
REFERENCES = Path("/reference-tests")


def mount_record(path):
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        left, right = line.split(" - ", 1)
        if left.split()[4] == str(path):
            fields = right.split()
            return {"source": fields[1], "filesystem": fields[0]}
    raise AssertionError(f"Missing Linux mount: {path}")


class StorageChecks(unittest.TestCase):
    def setUp(self):
        self.storage = DATA / str(uuid.uuid4())
        self.reference = REFERENCES / f"{uuid.uuid4()}.json"
        self.options = {
            "mount_path": str(DATA),
            "mount_source": mount_record(DATA)["source"],
        }
        bootstrap(self.storage, self.reference, **self.options)

    def open_store(self, **options):
        return AnonymousSessionStore(
            str(self.storage), str(self.reference), **(self.options | options)
        )

    def assert_startup_refused(self, **options):
        # Execute the real FastAPI lifespan in a separate Linux process.
        env = os.environ | {
            "QUOTA_STORAGE_PATH": str(self.storage),
            "ANONYMOUS_STORE_REFERENCE": str(self.reference),
            "ANONYMOUS_MOUNT_PATH": options.get("mount_path", str(DATA)),
            "ANONYMOUS_MOUNT_SOURCE": options.get(
                "mount_source", self.options["mount_source"]
            ),
            "ANONYMOUS_STORAGE_DEVELOPMENT": "false",
            "ANONYMOUS_COOKIE_SECURE": "true",
        }
        code = (
            "import asyncio\nfrom app.main import app, lifespan\n"
            "async def start():\n"
            "    async with lifespan(app):\n        pass\n"
            "asyncio.run(start())\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], env=env, capture_output=True, timeout=40
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"quota_storage_unavailable", result.stderr)

    def test_missing_mount(self):
        # An existing ordinary directory is not an independently mounted volume.
        self.assert_startup_refused(mount_path=str(self.storage))

    def test_wrong_mount_source(self):
        self.assert_startup_refused(mount_source="/dev/not-the-quota-volume")

    def test_both_files_missing(self):
        (self.storage / "quota-state-v1.json").unlink()
        (self.storage / "initialized-v1.json").unlink()
        self.assert_startup_refused()
        self.assertFalse((self.storage / "quota-state-v1.json").exists())

    def test_missing_reference(self):
        self.reference.unlink()
        self.assert_startup_refused()

    def test_partial_bootstrap(self):
        (self.storage / "initialized-v1.json").unlink()
        self.assert_startup_refused()
        with self.assertRaises(ValueError):
            bootstrap(self.storage, self.reference, **self.options)

    def test_wrong_uuid(self):
        self.reference.write_text(json.dumps({"store_id": str(uuid.uuid4())}))
        self.assert_startup_refused()

    def test_corrupt_ledger(self):
        (self.storage / "quota-state-v1.json").write_text("{broken")
        self.assert_startup_refused()

    def test_invalid_counts(self):
        path = self.storage / "quota-state-v1.json"
        state = json.loads(path.read_text())
        state["days"]["2026-09-28"] = {
            "personal": {},
            "session_ip": {},
            "session_count": -1,
        }
        path.write_text(json.dumps(state))
        self.assert_startup_refused()

    def test_second_process(self):
        ledger = self.open_store()
        try:
            self.assert_startup_refused()
        finally:
            ledger.close()

    def test_directory_fsync_unavailable(self):
        with patch("app.core.anonymous_session._sync_directory", side_effect=OSError):
            with self.assertRaises(SessionError):
                self.open_store()

    def test_bootstrap_requires_mount_before_writing(self):
        storage = DATA / str(uuid.uuid4())
        reference = REFERENCES / f"{uuid.uuid4()}.json"
        with self.assertRaises(ValueError):
            bootstrap(storage, reference, mount_path="/missing", mount_source="bad")
        self.assertFalse(storage.exists())
        self.assertFalse(reference.exists())

    def test_each_write_boundary_and_restart(self):
        # Importing test fixture installs no production API routes.
        from backend_fixture import fault_patch

        for stage in ("temporary", "file_fsync", "replace", "directory_fsync"):
            with self.subTest(stage=stage):
                ledger = self.open_store()
                token, identity = ledger.create("192.0.2.1")
                ledger.personal_count(identity, increment=True)
                before = copy.deepcopy(ledger.state)
                try:
                    with fault_patch(stage), self.assertRaises(SessionError):
                        ledger.personal_count(identity, increment=True)
                    self.assertFalse(ledger.healthy)
                    self.assertEqual(ledger.state, before)
                    with self.assertRaises(SessionError):
                        ledger.resolve(token)
                finally:
                    ledger.close()
                reopened = self.open_store()
                try:
                    # A failed directory fsync follows replace: conservatively
                    # retaining that unacknowledged increment is acceptable.
                    expected = 2 if stage == "directory_fsync" else 1
                    self.assertEqual(
                        reopened.personal_count(reopened.resolve(token)), expected
                    )
                finally:
                    reopened.close()


if __name__ == "__main__":
    assert sys.platform == "linux"
    assert mount_record(DATA)["filesystem"] not in ("9p", "virtiofs", "fuse.grpcfuse")
    unittest.main(verbosity=2)
