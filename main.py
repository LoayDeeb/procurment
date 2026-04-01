"""
Render-safe ASGI entrypoint.

This wrapper allows running:
    uvicorn main:app
from repository root, while the real app lives in backend/main.py.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_app():
    try:
        from backend.main import app as backend_app  # type: ignore

        return backend_app
    except Exception:
        backend_main = Path(__file__).resolve().parent / "backend" / "main.py"
        if not backend_main.exists():
            raise RuntimeError(f"Backend app file not found at: {backend_main}")

        spec = importlib.util.spec_from_file_location("backend_main_app", str(backend_main))
        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to create import spec for backend/main.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not hasattr(module, "app"):
            raise RuntimeError("Loaded backend/main.py but no 'app' object was found")
        return module.app


app = _load_app()
