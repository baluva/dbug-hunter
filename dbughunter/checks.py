"""The catalogue of database "bug" detectors.

Each check is a function ``check(db: Database) -> list[Finding]``. Register a new
one by adding it to :data:`CHECKS`. Keeping checks independent and pure (no shared
state) makes them trivial to unit-test one at a time.
"""
from __future__ import annotations

import re
from datetime import datetime

from .models import Database, Finding, q

# Columns whose *name* hints at a semantic meaning, used by heuristic checks.
_EMAIL_HINT = re.compile(r"(e?mail)", re.I)
_UNIQUE_HINT = re.compile(r"(email|username|user_name|login|slug|sku|code|barcode|isbn)", re.I)
_POSITIVE_HINT = re.compile(r"(price|amount|cost|qty|quantity|stock|age|count|total|salary|weight|height|duration)", re.I)
_DATE_HINT = re.compile(r"(date|_at$|_on$|time|birth|dob)", re.I)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DATE_FORMATS = ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S")

SAMPLE_LIMIT = 5


def _is_textual(col_type: str) -> bool:
    t = col_type.upper()
    return ("CHAR" in t) or ("TEXT" in t) or ("CLOB" in t) or t == ""


def _is_numeric(col_type: str) -> bool:
    t = col_type.upper()
    return any(k in t for k in ("INT", "REAL", "FLOA", "DOUB", "NUM", "DEC"))


# --------------------------------------------------------------------------
# Schema-level checks
# --------------------------------------------------------------------------
def check_no_primary_key(db: Database) -> list[Finding]:
    out = []
    for t in db.tables:
        if not t.primary_key:
            out.append(Finding(
                check="no_primary_key", severity="warning", category="schema",
                table=t.name, column=None,
                title="Table sans clé primaire",
                detail=f'La table "{t.name}" n\'a aucune clé primaire : risque de doublons '
                       "et de lignes non identifiables de façon unique.",
            ))
    return out


def check_empty_table(db: Database) -> list[Finding]:
    out = []
    for t in db.tables:
        if t.row_count == 0:
            out.append(Finding(
                check="empty_table", severity="info", category="schema",
                table=t.name, column=None,
                title="Table vide",
                detail=f'La table "{t.name}" ne contient aucune ligne.',
            ))
    return out


def check_fk_without_index(db: Database) -> list[Finding]:
    """Foreign-key columns without an index make joins and cascades slow."""
    out = []
    for t in db.tables:
        for fk in t.foreign_keys:
            if fk.column not in t.indexed_columns:
                out.append(Finding(
                    check="fk_without_index", severity="warning", category="performance",
                    table=t.name, column=fk.column,
                    title="Clé étrangère sans index",
                    detail=f'"{t.name}.{fk.column}" référence "{fk.ref_table}" mais n\'a pas '
                           "d'index : les jointures et vérifications d'intégrité seront lentes.",
                ))
    return out


# --------------------------------------------------------------------------
# Referential integrity
# --------------------------------------------------------------------------
def check_orphaned_foreign_keys(db: Database) -> list[Finding]:
    """Rows whose foreign key points to a parent row that does not exist."""
    out = []
    for t in db.tables:
        if not t.foreign_keys:
            continue
        try:
            rows = db.query(f"PRAGMA foreign_key_check({q(t.name)})")
        except Exception:
            continue
        if not rows:
            continue
        # rows: (table, rowid, parent, fkid)
        by_parent: dict[str, list] = {}
        for r in rows:
            by_parent.setdefault(r[2], []).append(r[1])
        for parent, rowids in by_parent.items():
            out.append(Finding(
                check="orphaned_foreign_keys", severity="critical", category="integrity",
                table=t.name, column=None,
                title="Clés étrangères orphelines",
                detail=f'{len(rowids)} ligne(s) de "{t.name}" référencent "{parent}" '
                       "sans ligne parente correspondante (intégrité référentielle rompue).",
                count=len(rowids),
                samples=[f"rowid={rid}" for rid in rowids[:SAMPLE_LIMIT]],
            ))
    return out


# --------------------------------------------------------------------------
# Duplicates & uniqueness
# --------------------------------------------------------------------------
def check_duplicate_rows(db: Database) -> list[Finding]:
    out = []
    for t in db.tables:
        if t.row_count == 0 or not t.columns:
            continue
        cols = ", ".join(q(c.name) for c in t.columns)
        sql = (
            f"SELECT COUNT(*) AS c FROM "
            f"(SELECT {cols}, COUNT(*) AS n FROM {q(t.name)} "
            f"GROUP BY {cols} HAVING n > 1)"
        )
        try:
            dup_groups = db.scalar(sql) or 0
            extra = db.scalar(
                f"SELECT IFNULL(SUM(n - 1), 0) FROM "
                f"(SELECT COUNT(*) AS n FROM {q(t.name)} GROUP BY {cols} HAVING n > 1)"
            ) or 0
        except Exception:
            continue
        if extra:
            out.append(Finding(
                check="duplicate_rows", severity="warning", category="integrity",
                table=t.name, column=None,
                title="Lignes en double",
                detail=f'{extra} ligne(s) en trop réparties sur {dup_groups} groupe(s) '
                       f'de doublons identiques dans "{t.name}".',
                count=int(extra),
            ))
    return out


def check_duplicate_unique_like(db: Database) -> list[Finding]:
    """Duplicate non-null values in columns that look like they should be unique."""
    out = []
    for t in db.tables:
        if t.row_count == 0:
            continue
        for c in t.columns:
            if c.pk or not _UNIQUE_HINT.search(c.name):
                continue
            col = q(c.name)
            try:
                dups = db.query(
                    f"SELECT {col} AS v, COUNT(*) AS n FROM {q(t.name)} "
                    f"WHERE {col} IS NOT NULL GROUP BY {col} HAVING n > 1 ORDER BY n DESC"
                )
            except Exception:
                continue
            if dups:
                total = sum(r["n"] - 1 for r in dups)
                out.append(Finding(
                    check="duplicate_unique_like", severity="warning", category="integrity",
                    table=t.name, column=c.name,
                    title="Valeurs dupliquées sur une colonne supposée unique",
                    detail=f'"{t.name}.{c.name}" contient {total} doublon(s) alors que son nom '
                           "suggère une valeur unique (manque-t-il une contrainte UNIQUE ?).",
                    count=total,
                    samples=[r["v"] for r in dups[:SAMPLE_LIMIT]],
                ))
    return out


# --------------------------------------------------------------------------
# Type & value quality
# --------------------------------------------------------------------------
def check_mixed_storage_types(db: Database) -> list[Finding]:
    """SQLite stores a type per value; a column holding several types is a real bug."""
    out = []
    for t in db.tables:
        if t.row_count == 0:
            continue
        for c in t.columns:
            col = q(c.name)
            try:
                rows = db.query(
                    f"SELECT typeof({col}) AS ty, COUNT(*) AS n FROM {q(t.name)} "
                    f"WHERE {col} IS NOT NULL GROUP BY ty"
                )
            except Exception:
                continue
            types = {r["ty"]: r["n"] for r in rows}
            if len(types) > 1:
                out.append(Finding(
                    check="mixed_storage_types", severity="critical", category="quality",
                    table=t.name, column=c.name,
                    title="Types de stockage mélangés dans une colonne",
                    detail=f'"{t.name}.{c.name}" mélange plusieurs types SQLite '
                           f"({', '.join(f'{k}×{v}' for k, v in types.items())}) : "
                           "source classique de bugs de tri et de comparaison.",
                    count=sum(types.values()),
                    samples=[f"{k}: {v}" for k, v in types.items()],
                ))
    return out


def check_null_values(db: Database) -> list[Finding]:
    out = []
    for t in db.tables:
        if t.row_count == 0:
            continue
        for c in t.columns:
            if c.notnull or c.pk:
                continue
            col = q(c.name)
            try:
                n = db.scalar(f"SELECT COUNT(*) FROM {q(t.name)} WHERE {col} IS NULL") or 0
            except Exception:
                continue
            if n:
                ratio = n / t.row_count
                # A FK or id-looking column with NULLs is more serious than a free-text one.
                is_keyish = any(fk.column == c.name for fk in t.foreign_keys) or c.name.lower().endswith("_id")
                sev = "warning" if (is_keyish or ratio > 0.5) else "info"
                out.append(Finding(
                    check="null_values", severity=sev, category="quality",
                    table=t.name, column=c.name,
                    title="Valeurs manquantes (NULL)",
                    detail=f'"{t.name}.{c.name}" contient {n} NULL ({ratio:.0%} des lignes).',
                    count=n,
                ))
    return out


def check_empty_strings(db: Database) -> list[Finding]:
    out = []
    for t in db.tables:
        if t.row_count == 0:
            continue
        for c in t.columns:
            if not _is_textual(c.declared_type):
                continue
            col = q(c.name)
            try:
                n = db.scalar(f"SELECT COUNT(*) FROM {q(t.name)} WHERE {col} = ''") or 0
            except Exception:
                continue
            if n:
                out.append(Finding(
                    check="empty_strings", severity="info", category="quality",
                    table=t.name, column=c.name,
                    title="Chaînes vides",
                    detail=f'"{t.name}.{c.name}" contient {n} chaîne(s) vide(s) "" '
                           "(devraient probablement être NULL).",
                    count=n,
                ))
    return out


def check_whitespace(db: Database) -> list[Finding]:
    out = []
    for t in db.tables:
        if t.row_count == 0:
            continue
        for c in t.columns:
            if not _is_textual(c.declared_type):
                continue
            col = q(c.name)
            try:
                rows = db.query(
                    f"SELECT {col} AS v FROM {q(t.name)} "
                    f"WHERE {col} IS NOT NULL AND {col} <> TRIM({col})"
                )
            except Exception:
                continue
            if rows:
                out.append(Finding(
                    check="whitespace", severity="info", category="quality",
                    table=t.name, column=c.name,
                    title="Espaces superflus",
                    detail=f'"{t.name}.{c.name}" : {len(rows)} valeur(s) avec des espaces '
                           "en début/fin (risque d'échec des comparaisons et regroupements).",
                    count=len(rows),
                    samples=[repr(r["v"]) for r in rows[:SAMPLE_LIMIT]],
                ))
    return out


def check_invalid_emails(db: Database) -> list[Finding]:
    out = []
    for t in db.tables:
        if t.row_count == 0:
            continue
        for c in t.columns:
            if not _EMAIL_HINT.search(c.name):
                continue
            col = q(c.name)
            try:
                rows = db.query(
                    f"SELECT {col} AS v FROM {q(t.name)} "
                    f"WHERE {col} IS NOT NULL AND {col} <> ''"
                )
            except Exception:
                continue
            bad = [r["v"] for r in rows if not _EMAIL_RE.match(str(r["v"]))]
            if bad:
                out.append(Finding(
                    check="invalid_emails", severity="warning", category="quality",
                    table=t.name, column=c.name,
                    title="Adresses e-mail invalides",
                    detail=f'"{t.name}.{c.name}" : {len(bad)} valeur(s) ne respectent pas '
                           "le format d'une adresse e-mail.",
                    count=len(bad),
                    samples=bad[:SAMPLE_LIMIT],
                ))
    return out


def _parse_date(value: str) -> datetime | None:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except (ValueError, TypeError):
            continue
    return None


def check_dates(db: Database) -> list[Finding]:
    out = []
    now = datetime.now()
    for t in db.tables:
        if t.row_count == 0:
            continue
        for c in t.columns:
            looks_date = _DATE_HINT.search(c.name) or "DATE" in c.declared_type or "TIME" in c.declared_type
            if not looks_date:
                continue
            col = q(c.name)
            try:
                rows = db.query(
                    f"SELECT {col} AS v FROM {q(t.name)} "
                    f"WHERE {col} IS NOT NULL AND {col} <> '' AND typeof({col}) = 'text'"
                )
            except Exception:
                continue
            invalid, future = [], []
            for r in rows:
                parsed = _parse_date(str(r["v"]))
                if parsed is None:
                    invalid.append(r["v"])
                elif parsed > now:
                    future.append(r["v"])
            if invalid:
                out.append(Finding(
                    check="invalid_dates", severity="warning", category="quality",
                    table=t.name, column=c.name,
                    title="Dates invalides",
                    detail=f'"{t.name}.{c.name}" : {len(invalid)} valeur(s) ne sont pas des '
                           "dates exploitables.",
                    count=len(invalid),
                    samples=invalid[:SAMPLE_LIMIT],
                ))
            if future:
                out.append(Finding(
                    check="future_dates", severity="info", category="quality",
                    table=t.name, column=c.name,
                    title="Dates dans le futur",
                    detail=f'"{t.name}.{c.name}" : {len(future)} date(s) postérieures à '
                           "aujourd'hui (souvent une erreur de saisie).",
                    count=len(future),
                    samples=[str(v) for v in future[:SAMPLE_LIMIT]],
                ))
    return out


def check_negative_values(db: Database) -> list[Finding]:
    out = []
    for t in db.tables:
        if t.row_count == 0:
            continue
        for c in t.columns:
            if not (_is_numeric(c.declared_type) and _POSITIVE_HINT.search(c.name)):
                continue
            col = q(c.name)
            try:
                rows = db.query(
                    f"SELECT {col} AS v FROM {q(t.name)} WHERE {col} < 0"
                )
            except Exception:
                continue
            if rows:
                out.append(Finding(
                    check="negative_values", severity="warning", category="quality",
                    table=t.name, column=c.name,
                    title="Valeurs négatives suspectes",
                    detail=f'"{t.name}.{c.name}" : {len(rows)} valeur(s) négative(s) sur une '
                           "colonne qui devrait être positive.",
                    count=len(rows),
                    samples=[r["v"] for r in rows[:SAMPLE_LIMIT]],
                ))
    return out


def check_outliers(db: Database) -> list[Finding]:
    """Flag numeric outliers using the inter-quartile range (IQR) rule."""
    out = []
    for t in db.tables:
        if t.row_count < 8:  # not enough data for a meaningful quartile
            continue
        for c in t.columns:
            if not _is_numeric(c.declared_type) or c.pk:
                continue
            col = q(c.name)
            try:
                values = [
                    r[0] for r in db.query(
                        f"SELECT {col} FROM {q(t.name)} WHERE {col} IS NOT NULL "
                        f"AND typeof({col}) IN ('integer','real') ORDER BY {col}"
                    )
                ]
            except Exception:
                continue
            if len(values) < 8:
                continue
            q1 = values[len(values) // 4]
            q3 = values[(len(values) * 3) // 4]
            iqr = q3 - q1
            if iqr <= 0:
                continue
            low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            outliers = [v for v in values if v < low or v > high]
            if outliers:
                out.append(Finding(
                    check="outliers", severity="info", category="quality",
                    table=t.name, column=c.name,
                    title="Valeurs aberrantes (outliers)",
                    detail=f'"{t.name}.{c.name}" : {len(outliers)} valeur(s) hors de '
                           f"l'intervalle attendu [{low:.2f}, {high:.2f}] (règle de l'IQR).",
                    count=len(outliers),
                    samples=[outliers[0], outliers[-1]],
                ))
    return out


# Order matters only for display grouping; severity drives the real sort later.
CHECKS = [
    check_orphaned_foreign_keys,
    check_mixed_storage_types,
    check_duplicate_rows,
    check_duplicate_unique_like,
    check_invalid_emails,
    check_dates,
    check_negative_values,
    check_no_primary_key,
    check_fk_without_index,
    check_null_values,
    check_whitespace,
    check_empty_strings,
    check_outliers,
    check_empty_table,
]
