import io
from functools import lru_cache

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from paddleocr import PaddleOCR


@lru_cache(maxsize=1)
def get_ocr_engine(lang: str = "fr") -> PaddleOCR:
    return PaddleOCR(use_angle_cls=True, lang=lang, show_log=False)


def extract_text_from_image(image_bytes: bytes, lang: str = "fr") -> dict:
    ocr_engine = get_ocr_engine(lang)

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    enhanced_image = ImageOps.autocontrast(image.convert("L")).convert("RGB")
    enhanced_image = enhanced_image.resize(
        (enhanced_image.width * 2, enhanced_image.height * 2), Image.Resampling.LANCZOS
    )
    enhanced_image = ImageEnhance.Contrast(enhanced_image).enhance(1.25)
    enhanced_image = enhanced_image.filter(ImageFilter.SHARPEN)

    candidates = [
        _run_ocr(ocr_engine, np.array(image)),
        _run_ocr(ocr_engine, np.array(enhanced_image)),
    ]
    lines, confidences = max(
        candidates,
        key=lambda candidate: sum(candidate[1]) if candidate[1] else 0.0,
    )

    return {
        "raw_text": "\n".join(lines),
        "confidence_scores": confidences,
    }


def _run_ocr(ocr_engine: PaddleOCR, image_array: np.ndarray) -> tuple[list[str], list[float]]:
    ocr_output = ocr_engine.ocr(image_array, cls=True)
    lines: list[str] = []
    confidences: list[float] = []

    if ocr_output and ocr_output[0]:
        for _box, (text, confidence) in ocr_output[0]:
            lines.append(text)
            confidences.append(float(confidence))

    return lines, confidences
