"""Unit tests for the detection engine. Run with:  pytest"""
import os
import sqlite3

import pytest

from dbughunter.detector import scan_database
from dbughunter.models import Database
from dbughunter import checks


def make_db(tmp_path, script: str) -> str:
    path = os.path.join(tmp_path, "t.db")
    conn = sqlite3.connect(path)
    conn.executescript(script)
    conn.commit()
    conn.close()
    return path


def run_check(tmp_path, script, fn):
    db = Database(make_db(tmp_path, script))
    try:
        return fn(db)
    finally:
        db.close()


def test_orphaned_foreign_keys(tmp_path):
    findings = run_check(tmp_path, """
        CREATE TABLE parent (id INTEGER PRIMARY KEY);
        CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER
            REFERENCES parent(id));
        INSERT INTO parent VALUES (1);
        INSERT INTO child VALUES (1, 1), (2, 999);
    """, checks.check_orphaned_foreign_keys)
    assert len(findings) == 1
    assert findings[0].severity == "critical"
    assert findings[0].count == 1


def test_duplicate_rows(tmp_path):
    findings = run_check(tmp_path, """
        CREATE TABLE t (a INTEGER, b TEXT);
        INSERT INTO t VALUES (1, 'x'), (1, 'x'), (1, 'x'), (2, 'y');
    """, checks.check_duplicate_rows)
    assert findings and findings[0].count == 2  # two extra copies of (1,'x')


def test_mixed_storage_types(tmp_path):
    findings = run_check(tmp_path, """
        CREATE TABLE t (id INTEGER PRIMARY KEY, val);
        INSERT INTO t VALUES (1, 10), (2, 'oops'), (3, 30);
    """, checks.check_mixed_storage_types)
    assert findings and findings[0].column == "val"
    assert findings[0].severity == "critical"


def test_invalid_emails(tmp_path):
    findings = run_check(tmp_path, """
        CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT);
        INSERT INTO users VALUES (1, 'ok@example.com'), (2, 'nope'), (3, 'a@@b');
    """, checks.check_invalid_emails)
    assert findings and findings[0].count == 2


def test_negative_values(tmp_path):
    findings = run_check(tmp_path, """
        CREATE TABLE p (id INTEGER PRIMARY KEY, price REAL);
        INSERT INTO p VALUES (1, 5.0), (2, -3.0);
    """, checks.check_negative_values)
    assert findings and findings[0].count == 1


def test_no_primary_key(tmp_path):
    findings = run_check(tmp_path, """
        CREATE TABLE haspk (id INTEGER PRIMARY KEY);
        CREATE TABLE nopk (a INTEGER, b TEXT);
    """, checks.check_no_primary_key)
    assert {f.table for f in findings} == {"nopk"}


def test_duplicate_unique_like(tmp_path):
    findings = run_check(tmp_path, """
        CREATE TABLE u (id INTEGER PRIMARY KEY, email TEXT);
        INSERT INTO u VALUES (1, 'a@b.com'), (2, 'a@b.com'), (3, 'c@d.com');
    """, checks.check_duplicate_unique_like)
    assert findings and findings[0].count == 1


def test_clean_db_has_no_findings(tmp_path):
    report = scan_database(make_db(tmp_path, """
        CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        INSERT INTO t VALUES (1, 'alice'), (2, 'bob');
    """))
    assert report["summary"]["findings"] == 0
    assert report["summary"]["score"] == 100


def test_full_scan_report_shape(tmp_path):
    report = scan_database(make_db(tmp_path, """
        CREATE TABLE parent (id INTEGER PRIMARY KEY);
        CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id));
        INSERT INTO child VALUES (1, 42);
    """))
    assert report["summary"]["score"] < 100
    assert report["summary"]["critical"] >= 1
    assert "findings" in report and isinstance(report["findings"], list)
    assert report["summary"]["checks_run"] == len(checks.CHECKS)
