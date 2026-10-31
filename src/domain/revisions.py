"""Stable record identity shared by manual edits and human splits."""

import hashlib
import json
from dataclasses import asdict
from typing import Any

from .models import Finding


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def finding_revision(finding: Finding) -> str:
    return digest(asdict(finding))
