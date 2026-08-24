#!/usr/bin/env python3
"""Save a full-screen screenshot. Usage: python tools/screenshot.py [out.png]"""

import sys
from datetime import datetime
from pathlib import Path

from PIL import ImageGrab

out = sys.argv[1] if len(sys.argv) > 1 else None
img = ImageGrab.grab()
if out is None:
    out = Path(__file__).resolve().parent.parent / "logs" / (
        "shot-%s.png" % datetime.now().strftime("%H%M%S"))
img.save(out)
print(out)
