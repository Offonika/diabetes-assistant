import re


def extract_nutrition_info(text: str) -> tuple[float | None, float | None]:
    """Parse carbs and XE values from Vision text.

    Returns a tuple ``(carbs, xe)`` where either value may be ``None`` if it
    could not be determined from ``text``.
    """
    carbs = xe = None

    m = re.search(r"углевод[^\d]*:\s*([\d.,]+)\s*г", text, re.IGNORECASE)
    if m:
        carbs = float(m.group(1).replace(",", "."))

    m = re.search(r"\bх[еe][^\d]*:\s*([\d.,]+)", text, re.IGNORECASE)
    if m:
        xe = float(m.group(1).replace(",", "."))

    if carbs is None:
        rng = re.search(r"(\d+[.,]?\d*)\s*[–-]\s*(\d+[.,]?\d*)\s*г", text, re.IGNORECASE)
        if rng:
            carbs = (float(rng.group(1).replace(",", ".")) + float(rng.group(2).replace(",", "."))) / 2

    if xe is None:
        rng = re.search(r"(\d+[.,]?\d*)\s*[–-]\s*(\d+[.,]?\d*)\s*(?:ХЕ|XE)", text, re.IGNORECASE)
        if rng:
            xe = (float(rng.group(1).replace(",", ".")) + float(rng.group(2).replace(",", "."))) / 2

    return carbs, xe
