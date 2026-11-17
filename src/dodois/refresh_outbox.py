"""Encrypted durable refresh handoff, serialized per country across processes.

The requested marker is committed before an irreversible HTTP refresh. A ready
pair is committed before database retries. An unresolved requested marker is
never permission to reuse its refresh token after a restart.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.db import secret_crypto
from src.db.errors import DbError
from src.domain.dodois import CONTOURS, is_country

from .client import TokenPair

DIRECTORY = "dodois-refresh"
LOCK_TIMEOUT_SECONDS = 10.0
MAX_BYTES = 128 * 1024


class OutboxError(DbError):
    """The handoff is unavailable or invalid; messages contain no secret values."""


@dataclass(frozen=True, repr=False)
class Pending:
    country: str
    contour: str
    linked_at: datetime
    moment: datetime
    source_hash: str
    pair: TokenPair | None = None

    def __repr__(self) -> str:
        return "Pending(<hidden>)"


def _sync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _root() -> Path:
    raw = os.environ.get("STATE_DIR")
    if not raw or not Path(raw).is_dir():
        raise OutboxError("Dodo IS: постоянный STATE_DIR недоступен")
    state = Path(raw).resolve()
    root = state / DIRECTORY
    if root.is_symlink():
        raise OutboxError("Dodo IS: каталог очереди не должен быть ссылкой")
    root.mkdir(mode=0o700, exist_ok=True)
    os.chmod(root, 0o700)
    _sync_dir(state)
    return root


def _aad(country: str) -> str:
    return f"dodois.refresh-outbox.v1.{country}"


def _atomic(path: Path, payload: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".refresh-")
    try:
        with os.fdopen(descriptor, "wb") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        _sync_dir(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


class Journal:
    def __init__(self, root: Path, country: str) -> None:
        self.country = country
        self.path = root / f"{country}.bin"

    def preflight(self) -> None:
        """Check encryption, write and fsync before consuming a provider token."""
        probe = self.path.with_suffix(".probe")
        _atomic(probe, secret_crypto.encrypt(_aad(self.country), "probe"))
        probe.unlink()
        _sync_dir(probe.parent)

    def read(self) -> Pending | None:
        if not self.path.exists():
            return None
        try:
            blob = self.path.read_bytes()
            if len(blob) > MAX_BYTES:
                raise OutboxError("Dodo IS: очередь продления повреждена")
            raw = json.loads(secret_crypto.decrypt(_aad(self.country), blob))
            if (
                raw["version"] != 1
                or raw["country"] != self.country
                or raw.get("contour") not in CONTOURS
                or not isinstance(raw.get("source_hash"), str)
                or len(raw["source_hash"]) != 64
            ):
                raise ValueError
            pair_raw = raw.get("pair")
            pair = None if pair_raw is None else TokenPair(**pair_raw)
            if pair is not None and (
                not isinstance(pair.access, str)
                or not pair.access
                or not isinstance(pair.refresh, str)
                or not pair.refresh
                or not isinstance(pair.expires_in, int)
                or pair.expires_in <= 0
                or (pair.scope is not None and not isinstance(pair.scope, str))
            ):
                raise ValueError
            return Pending(
                country=self.country,
                contour=raw["contour"],
                linked_at=datetime.fromisoformat(raw["linked_at"]),
                moment=datetime.fromisoformat(raw["moment"]),
                source_hash=raw["source_hash"],
                pair=pair,
            )
        except (ValueError, TypeError, KeyError, secret_crypto.SecretCryptoError):
            raise OutboxError("Dodo IS: очередь продления не открылась") from None

    def write(self, pending: Pending) -> None:
        raw: dict[str, Any] = asdict(pending)
        raw.update(
            version=1, linked_at=pending.linked_at.isoformat(), moment=pending.moment.isoformat()
        )
        blob = secret_crypto.encrypt(_aad(self.country), json.dumps(raw))
        _atomic(self.path, blob)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
        _sync_dir(self.path.parent)


@contextmanager
def locked(country: str) -> Iterator[Journal]:
    """One country lock encloses journal, provider request and DB handoff."""
    if not is_country(country):
        raise OutboxError("Dodo IS: неверный код страны")
    try:
        root = _root()
        descriptor = os.open(
            root / f"{country}.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
    except OSError:
        raise OutboxError("Dodo IS: очередь продления недоступна") from None
    try:
        os.fchmod(descriptor, 0o600)
        deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise OutboxError("Dodo IS: продление страны уже выполняется") from None
                time.sleep(0.01)
        yield Journal(root, country)
    except (OSError, secret_crypto.SecretCryptoError):
        raise OutboxError("Dodo IS: защищённая запись продления не удалась") from None
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
