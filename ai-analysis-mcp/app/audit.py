from __future__ import annotations

import json
from pathlib import Path

from app.config import settings


def append_audit_record(record: dict) -> None:
    path = Path(settings.audit_log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def read_recent_validations(limit: int) -> list[str]:
    path = Path(settings.audit_log_path)
    if not path.exists():
        return []
    lines = path.read_text().splitlines()[-limit:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line)["validation"])
        except (json.JSONDecodeError, KeyError):
            continue
    return out
