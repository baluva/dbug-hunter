"""Scan orchestration: run every check against a database and build a report."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from .checks import CHECKS
from .models import Database, Finding

_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
_SCORE_WEIGHT = {"critical": 12, "warning": 4, "info": 1}
_SCORE_CAP = {"critical": 70, "warning": 40, "info": 15}


def _health_score(findings: list[Finding]) -> int:
    """A 0-100 score: 100 = clean, lower = more/worse problems (with diminishing hits)."""
    penalty = 0.0
    for sev, weight in _SCORE_WEIGHT.items():
        n = sum(1 for f in findings if f.severity == sev)
        penalty += min(n * weight, _SCORE_CAP[sev])
    return max(0, round(100 - penalty))


def scan_database(path: str) -> dict:
    """Run all checks on the SQLite file at *path* and return a JSON-ready report."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    db = Database(path)
    try:
        findings: list[Finding] = []
        for check in CHECKS:
            try:
                findings.extend(check(db))
            except Exception as exc:  # one broken check must not kill the whole scan
                findings.append(Finding(
                    check=check.__name__, severity="info", category="quality",
                    table="-", column=None,
                    title="Vérification non aboutie",
                    detail=f"Le contrôle {check.__name__} a échoué : {exc}",
                ))

        findings.sort(key=lambda f: (_SEVERITY_ORDER.get(f.severity, 9), -f.count, f.table))

        counts = {
            "critical": sum(1 for f in findings if f.severity == "critical"),
            "warning": sum(1 for f in findings if f.severity == "warning"),
            "info": sum(1 for f in findings if f.severity == "info"),
        }

        report = {
            "database": os.path.basename(path),
            "scanned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "summary": {
                "tables": len(db.tables),
                "rows": db.total_rows,
                "checks_run": len(CHECKS),
                "findings": len(findings),
                "score": _health_score(findings),
                **counts,
            },
            "tables": [
                {
                    "name": t.name,
                    "rows": t.row_count,
                    "columns": len(t.columns),
                    "primary_key": t.primary_key,
                    "foreign_keys": [
                        {"column": fk.column, "references": f"{fk.ref_table}.{fk.ref_column}"}
                        for fk in t.foreign_keys
                    ],
                }
                for t in db.tables
            ],
            "findings": [f.to_dict() for f in findings],
        }
        return report
    finally:
        db.close()
