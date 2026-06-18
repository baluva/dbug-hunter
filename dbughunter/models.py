"""Data models and SQLite introspection helpers used by the detection engine."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Finding:
    """A single problem detected in a database."""

    check: str          # machine name of the check that produced it
    severity: str       # "critical" | "warning" | "info"
    category: str       # "integrity" | "schema" | "quality" | "performance"
    table: str
    column: str | None
    title: str
    detail: str
    count: int = 0                      # how many rows/values are affected
    samples: list[Any] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ColumnInfo:
    name: str
    declared_type: str
    notnull: bool
    default: Any
    pk: int  # 0 = not part of PK, >0 = position in PK


@dataclass
class ForeignKey:
    column: str          # local column ("from")
    ref_table: str       # referenced table
    ref_column: str      # referenced column ("to")


@dataclass
class TableInfo:
    name: str
    columns: list[ColumnInfo]
    foreign_keys: list[ForeignKey]
    indexed_columns: set[str]
    row_count: int

    @property
    def primary_key(self) -> list[str]:
        return [c.name for c in self.columns if c.pk]

    def column(self, name: str) -> ColumnInfo | None:
        return next((c for c in self.columns if c.name == name), None)


class Database:
    """Thin wrapper around a SQLite connection that caches schema introspection.

    A check receives one of these and queries it instead of touching raw PRAGMAs.
    """

    def __init__(self, path: str):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.tables: list[TableInfo] = self._introspect()

    # -- introspection -----------------------------------------------------
    def _introspect(self) -> list[TableInfo]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        names = [r[0] for r in cur.fetchall()]

        tables: list[TableInfo] = []
        for name in names:
            columns = [
                ColumnInfo(
                    name=r["name"],
                    declared_type=(r["type"] or "").upper(),
                    notnull=bool(r["notnull"]),
                    default=r["dflt_value"],
                    pk=r["pk"],
                )
                for r in cur.execute(f'PRAGMA table_info("{name}")').fetchall()
            ]

            foreign_keys = [
                ForeignKey(column=r["from"], ref_table=r["table"], ref_column=r["to"])
                for r in cur.execute(f'PRAGMA foreign_key_list("{name}")').fetchall()
            ]

            indexed: set[str] = {c.name for c in columns if c.pk}
            for idx in cur.execute(f'PRAGMA index_list("{name}")').fetchall():
                for ic in cur.execute(f'PRAGMA index_info("{idx["name"]}")').fetchall():
                    if ic["name"]:
                        indexed.add(ic["name"])

            try:
                row_count = cur.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            except sqlite3.DatabaseError:
                row_count = 0

            tables.append(
                TableInfo(
                    name=name,
                    columns=columns,
                    foreign_keys=foreign_keys,
                    indexed_columns=indexed,
                    row_count=row_count,
                )
            )
        return tables

    # -- convenience -------------------------------------------------------
    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def scalar(self, sql: str, params: tuple = ()):
        row = self.conn.execute(sql, params).fetchone()
        return row[0] if row else None

    @property
    def total_rows(self) -> int:
        return sum(t.row_count for t in self.tables)

    def close(self) -> None:
        self.conn.close()


def q(identifier: str) -> str:
    """Quote a SQL identifier (table/column) safely for interpolation."""
    return '"' + identifier.replace('"', '""') + '"'
