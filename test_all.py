#!/usr/bin/env python3
"""One command to run every test:

    python3 test_all.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "tests"))
sys.path.insert(0, HERE)

from test_movie_lovers import main   # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
