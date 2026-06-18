"""Convenience launcher:  python run.py  ->  http://127.0.0.1:8000"""
import os
import webbrowser

import uvicorn

if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    if os.environ.get("OPEN_BROWSER", "1") == "1":
        webbrowser.open(f"http://{host}:{port}")
    uvicorn.run("dbughunter.webapp:app", host=host, port=port, reload=False)
