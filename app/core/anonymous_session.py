"""Persistent anonymous identities. Runtime never initializes an empty ledger."""

import copy
import hashlib
import json
import os
import re
import secrets
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

TOKEN_PATTERN = re.compile(r"anon_v1_[A-Za-z0-9_-]{43}\Z")
SESSION_LIFETIME = 2_592_000


class SessionError(Exception):
    """Public, controlled identity or storage failure."""

    def __init__(self, code: str, status: int = 401, retry_after: int | None = None):
        self.code = code
        self.status = status
        self.retry_after = retry_after
        super().__init__(code)


def _sync_directory(path: Path, development: bool) -> None:
    if os.name == "nt" and development:
        return  # Windows development makes no power-loss durability claim.
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_atomic(path: Path, data: dict, development: bool) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".quota-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, separators=(",", ":"), allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent, development)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def verify_mount(storage: Path, reference: Path, mount_path: str, source: str) -> None:
    """Require the configured quota volume before provisioning or serving."""
    if os.name != "posix" or not Path("/proc/self/mountinfo").exists():
        raise ValueError("Production requires Linux mount verification")
    mount = Path(mount_path).resolve() if mount_path else None
    if not mount or not source or mount == Path("/"):
        raise ValueError("Explicit quota mount and source required")
    if mount != storage and mount not in storage.parents:
        raise ValueError("Quota path is outside expected mount")
    if mount == reference or mount in reference.parents:
        raise ValueError("Reference is on quota mount")

    def unescape(value):
        return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), value)

    entries = Path("/proc/self/mountinfo").read_text().splitlines()
    matches = []
    for entry in entries:
        left, right = entry.split(" - ", 1)
        fields = left.split()
        if unescape(fields[4]) == str(mount):
            matches.append(unescape(right.split()[1]))
    if matches != [source]:
        raise ValueError("Expected persistent mount is missing or mismatched")


def bootstrap(
    storage: Path,
    reference: Path,
    *,
    development: bool = False,
    mount_path: str = "",
    mount_source: str = "",
) -> str:
    """Create a new store while stopped; partial provisioning requires inspection."""
    storage, reference = storage.resolve(), reference.resolve()
    if (
        storage == reference
        or storage in reference.parents
        or reference in storage.parents
    ):
        raise ValueError("The reference must be outside the quota volume")
    if os.name != "posix" and not development:
        raise ValueError("Production storage requires Linux directory fsync")
    if not development:
        verify_mount(storage, reference, mount_path, mount_source)
    if reference.exists() or (storage.exists() and any(storage.iterdir())):
        raise ValueError("Refusing to overwrite existing or partial provisioning")
    storage.mkdir(parents=True, exist_ok=True)
    reference.parent.mkdir(parents=True, exist_ok=True)
    _sync_directory(storage.parent, development)
    _sync_directory(reference.parent.parent, development)
    store_id = str(uuid.uuid4())
    _write_atomic(
        storage / "quota-state-v1.json",
        {"schema_version": 1, "store_id": store_id, "sessions": {}, "days": {}},
        development,
    )
    _write_atomic(storage / "initialized-v1.json", {"store_id": store_id}, development)
    _write_atomic(reference, {"store_id": store_id}, development)
    return store_id


class AnonymousSessionStore:
    """One process owns a unified ledger; all writes share a thread lock."""

    def __init__(
        self,
        storage: str,
        reference: str,
        *,
        development: bool = False,
        mount_path: str = "",
        mount_source: str = "",
        clock=time.time,
    ):
        self.storage = Path(storage).resolve()
        self.reference = Path(reference).resolve()
        self.development = development
        self.clock = clock
        self._lock = threading.RLock()
        self._file_lock = None
        self.healthy = False
        try:
            if (
                self.storage == self.reference
                or self.storage in self.reference.parents
                or self.reference in self.storage.parents
            ):
                raise ValueError("Reference is not independent")
            if not development:
                verify_mount(self.storage, self.reference, mount_path, mount_source)
            self._acquire_process_lock()
            _sync_directory(self.storage, development)
            with self.reference.open(encoding="utf-8") as stream:
                expected = json.load(stream)["store_id"]
            with (self.storage / "initialized-v1.json").open(
                encoding="utf-8"
            ) as stream:
                marker = json.load(stream)["store_id"]
            with (self.storage / "quota-state-v1.json").open(
                encoding="utf-8"
            ) as stream:
                state = json.load(stream)
            if marker != expected or state["store_id"] != expected:
                raise ValueError("Store identity mismatch")
            uuid.UUID(expected)
            self._validate(state)
            # Probe the same write/replace/fsync boundary used by future commits.
            probe = self.storage / ".quota-write-probe"
            _write_atomic(probe, {"store_id": expected}, development)
            probe.unlink()
            _sync_directory(self.storage, development)
            self.state = state
            self.healthy = True
        except Exception:
            self.close()
            raise SessionError("quota_storage_unavailable", 503) from None

    def _acquire_process_lock(self) -> None:
        stream = (self.storage / ".quota.lock").open("a+b")
        self._file_lock = stream
        if os.name == "nt":
            import msvcrt

            stream.seek(0)
            if not stream.read(1):
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _validate(state: dict) -> None:
        if state["schema_version"] != 1:
            raise ValueError("Unknown schema")
        if not isinstance(state["sessions"], dict) or not isinstance(
            state["days"], dict
        ):
            raise ValueError("Invalid ledger")
        for digest, session in state["sessions"].items():
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("Invalid identity digest")
            for field in ("created_at", "expires_at"):
                if type(session[field]) is not int or session[field] < 0:
                    raise ValueError("Invalid expiry")
            if session["expires_at"] - session["created_at"] != SESSION_LIFETIME:
                raise ValueError("Invalid lifetime")
        for day, record in state["days"].items():
            datetime.strptime(day, "%Y-%m-%d")
            for group in ("personal", "session_ip"):
                if not isinstance(record[group], dict):
                    raise ValueError("Invalid daily counts")
                for key, value in record[group].items():
                    if not re.fullmatch(r"[0-9a-f]{64}", key):
                        raise ValueError("Invalid counter identity")
                    if type(value) is not int or value < 0:
                        raise ValueError("Invalid count")
            if type(record["session_count"]) is not int or record["session_count"] < 0:
                raise ValueError("Invalid creation count")

    def close(self) -> None:
        self.healthy = False
        if self._file_lock is not None:
            self._file_lock.close()
            self._file_lock = None

    def _ensure_healthy(self) -> None:
        if not self.healthy:
            raise SessionError("quota_storage_unavailable", 503)

    def _commit(self, state: dict) -> None:
        self._ensure_healthy()
        try:
            _write_atomic(self.storage / "quota-state-v1.json", state, self.development)
        except Exception:
            self.healthy = False
            raise SessionError("quota_storage_unavailable", 503) from None
        self.state = state

    def resolve(self, token: str) -> dict:
        """Validate an opaque credential; never derive identity from request IP."""
        with self._lock:
            self._ensure_healthy()
            if not TOKEN_PATTERN.fullmatch(token):
                raise SessionError("anonymous_session_invalid")
            digest = hashlib.sha256(token.encode("ascii")).hexdigest()
            session = self.state["sessions"].get(digest)
            if session is None:
                raise SessionError("anonymous_session_invalid")
            if self.clock() >= session["expires_at"]:
                raise SessionError("anonymous_session_expired")
            return {"quota_ref": digest, **session}

    def _day(self) -> str:
        return datetime.fromtimestamp(self.clock(), timezone.utc).strftime("%Y-%m-%d")

    def _daily(self, state: dict) -> dict:
        return state["days"].setdefault(
            self._day(), {"personal": {}, "session_ip": {}, "session_count": 0}
        )

    def create(self, source: str) -> tuple[str, dict]:
        """Durably create an identity with daily creation limits."""
        with self._lock:
            self._ensure_healthy()
            state = copy.deepcopy(self.state)
            daily = self._daily(state)
            source_hash = hashlib.sha256(source.encode()).hexdigest()
            count = daily["session_ip"].get(source_hash, 0)
            if count >= 300 or daily["session_count"] >= 1000:
                raise SessionError("rate_limited", 429, self.seconds_until_reset())
            token = "anon_v1_" + secrets.token_urlsafe(32)
            digest = hashlib.sha256(token.encode()).hexdigest()
            now = int(self.clock())
            record = {"created_at": now, "expires_at": now + SESSION_LIFETIME}
            state["sessions"][digest] = record
            daily["session_ip"][source_hash] = count + 1
            daily["session_count"] += 1
            for old_digest, old in list(state["sessions"].items()):
                if old["expires_at"] + 7 * 86400 <= now:
                    del state["sessions"][old_digest]
                    for old_day in state["days"].values():
                        old_day["personal"].pop(old_digest, None)
            self._commit(state)
            return token, {"quota_ref": digest, **record}

    def personal_count(self, identity: dict, *, increment=False, limit=5) -> int:
        """Step 2 personal identity accounting; global admission follows in step 3."""
        with self._lock:
            self._ensure_healthy()
            state = copy.deepcopy(self.state)
            personal = self._daily(state)["personal"]
            count = personal.get(identity["quota_ref"], 0)
            if increment:
                if count >= limit:
                    raise SessionError(
                        "quota_exceeded", 429, self.seconds_until_reset()
                    )
                count += 1
                personal[identity["quota_ref"]] = count
                self._commit(state)
            return count

    def seconds_until_reset(self) -> int:
        """UTC day boundary shared by daily admission failures."""
        return max(1, int(86400 - self.clock() % 86400))
