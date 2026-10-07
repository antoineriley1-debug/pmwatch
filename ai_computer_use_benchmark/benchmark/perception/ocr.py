"""Optional OCR used to ground element labels to precise on-screen text
positions. Works only from the pixels on screen; if Tesseract is not
installed, perception falls back to the vision model's own coordinates."""
from __future__ import annotations

from dataclasses import dataclass

from ..core import text_similarity


@dataclass
class OcrLine:
    text: str
    bbox: tuple[int, int, int, int]


class OcrEngine:
    def __init__(self):
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            self._tess = pytesseract
        except Exception:
            self._tess = None

    @property
    def available(self) -> bool:
        return self._tess is not None

    def lines(self, image, offset=(0, 0)) -> list[OcrLine]:
        if not self._tess:
            return []
        data = self._tess.image_to_data(image, output_type=self._tess.Output.DICT)
        grouped: dict[tuple, list[int]] = {}
        for i, word in enumerate(data["text"]):
            if not word.strip():
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            grouped.setdefault(key, []).append(i)
        out = []
        ox, oy = offset
        for idxs in grouped.values():
            text = " ".join(data["text"][i] for i in idxs)
            x0 = min(data["left"][i] for i in idxs)
            y0 = min(data["top"][i] for i in idxs)
            x1 = max(data["left"][i] + data["width"][i] for i in idxs)
            y1 = max(data["top"][i] + data["height"][i] for i in idxs)
            out.append(OcrLine(text, (x0 + ox, y0 + oy, x1 + ox, y1 + oy)))
        return out

    def locate_label(self, image, label: str, near_bbox: tuple[int, int, int, int]):
        """Find `label` as text inside an expanded region around `near_bbox`
        (full-resolution image pixels). Returns the text bbox or None."""
        if not self._tess or not label.strip():
            return None
        x0, y0, x1, y1 = near_bbox
        pad_x, pad_y = max(20, (x1 - x0) // 2), max(12, (y1 - y0) // 2)
        rx0, ry0 = max(0, x0 - pad_x), max(0, y0 - pad_y)
        rx1, ry1 = min(image.width, x1 + pad_x), min(image.height, y1 + pad_y)
        if rx1 <= rx0 or ry1 <= ry0:
            return None
        best, best_score = None, 0.0
        for line in self.lines(image.crop((rx0, ry0, rx1, ry1)), offset=(rx0, ry0)):
            score = text_similarity(line.text, label)
            if score > best_score:
                best, best_score = line, score
        return best.bbox if best and best_score >= 0.7 else None
