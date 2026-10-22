"""Compatibility entry point for the current REARM business smoke test."""
from pathlib import Path
import runpy
if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("shop_smoke.py")), run_name="__main__")
