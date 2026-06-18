"""FastAPI application exposing the scanner as a small web app.

Routes
------
GET  /             -> the single-page UI
POST /api/scan     -> upload a .db/.sqlite file, get a JSON report back
GET  /api/demo     -> scan the bundled buggy demo database
GET  /api/health   -> liveness probe
"""
from __future__ import annotations

import os
import sqlite3
import tempfile

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .detector import scan_database

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(BASE_DIR, "web")
DEMO_DB = os.path.join(BASE_DIR, "data", "demo_buggy.db")

MAX_BYTES = 50 * 1024 * 1024  # 50 MB upload ceiling
ALLOWED_EXT = {".db", ".sqlite", ".sqlite3", ".db3"}

app = FastAPI(title="DBug Hunter", version=__version__)


def _looks_like_sqlite(path: str) -> bool:
    with open(path, "rb") as fh:
        return fh.read(16) == b"SQLite format 3\x00"


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(os.path.join(WEB_DIR, "index.html"))


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": __version__, "demo_available": os.path.exists(DEMO_DB)}


@app.get("/api/demo")
def demo() -> JSONResponse:
    if not os.path.exists(DEMO_DB):
        raise HTTPException(status_code=404, detail="Base de démo introuvable. "
                            "Lancez d'abord scripts/make_demo_db.py.")
    report = scan_database(DEMO_DB)
    report["demo"] = True
    return JSONResponse(report)


@app.post("/api/scan")
async def scan(file: UploadFile = File(...)) -> JSONResponse:
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(status_code=400,
                            detail=f"Extension non supportée ({ext or 'aucune'}). "
                                   f"Formats acceptés : {', '.join(sorted(ALLOWED_EXT))}.")

    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="Fichier trop volumineux (max 50 Mo).")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    try:
        tmp.write(data)
        tmp.close()
        if not _looks_like_sqlite(tmp.name):
            raise HTTPException(status_code=400,
                                detail="Ce fichier n'est pas une base SQLite valide.")
        try:
            report = scan_database(tmp.name)
        except sqlite3.DatabaseError as exc:
            raise HTTPException(status_code=400, detail=f"Base illisible : {exc}")
        report["database"] = file.filename or report["database"]
        return JSONResponse(report)
    finally:
        os.unlink(tmp.name)


# Static assets (css/js). Mounted last so it never shadows the API routes above.
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
