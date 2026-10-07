"""Full-screen capture (spec section 3)."""
from __future__ import annotations

import io
import time

from PIL import Image, ImageChops

from ..core import Screenshot


class ScreenCapture:
    def __init__(self, monitor_index: int = 1):
        self.monitor_index = monitor_index
        self._sct = None

    def _mss(self):
        if self._sct is None:
            import mss  # imported lazily so the rest of the package loads without a display
            self._sct = mss.mss()
        return self._sct

    def capture(self) -> Screenshot:
        sct = self._mss()
        monitor = sct.monitors[self.monitor_index]
        raw = sct.grab(monitor)
        image = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        return Screenshot(image=image, left=monitor["left"], top=monitor["top"], taken_at=time.time())


def encode_for_model(image: Image.Image, max_edge: int) -> tuple[bytes, float]:
    """Downscale to the model's working size. Returns PNG bytes and the factor
    that maps model-image pixels back to full-resolution pixels."""
    width, height = image.size
    scale = max(width, height) / max_edge if max(width, height) > max_edge else 1.0
    if scale > 1.0:
        image = image.resize((round(width / scale), round(height / scale)), Image.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), scale


def changed_fraction(before: Image.Image, after: Image.Image, region=None, threshold: int = 24) -> float:
    """Fraction of pixels that visibly changed between two screenshots
    (optionally inside a region given in full-resolution image pixels)."""
    if before.size != after.size:
        return 1.0
    if region:
        x0, y0, x1, y1 = (int(v) for v in region)
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(before.width, x1), min(before.height, y1)
        if x1 <= x0 or y1 <= y0:
            return 0.0
        before, after = before.crop((x0, y0, x1, y1)), after.crop((x0, y0, x1, y1))
    small = (max(1, before.width // 4), max(1, before.height // 4))
    a = before.convert("L").resize(small)
    b = after.convert("L").resize(small)
    diff = ImageChops.difference(a, b).point(lambda p: 255 if p > threshold else 0)
    histogram = diff.histogram()
    return histogram[255] / float(small[0] * small[1])
