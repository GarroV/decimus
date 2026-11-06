"""Отпечаток состояния проверки: поймать правку между «увидел» и «запечатал»."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from .models import Inspection


def revision(inspection: Inspection) -> str:
    """Detect edits since the auditor reviewed this run without exposing its content."""
    content = json.dumps(asdict(inspection), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(content.encode()).hexdigest()
