"""Vercel serverless entrypoint — exposes the FastAPI ASGI app."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backend.app import app  # noqa: E402

# Vercel's @vercel/python runtime serves a module-level ASGI `app`.
