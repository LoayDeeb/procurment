"""
Render-safe ASGI entrypoint.

This wrapper allows running:
    uvicorn main:app
from repository root, while the real app lives in backend/main.py.
"""

from backend.main import app  # re-export for ASGI servers

