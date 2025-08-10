"""Утилиты для расчёта болюса и разбора пищевой информации."""

from dataclasses import dataclass
import re

# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------
# Base pattern for numeric values with optional decimal part (``"1"``, ``"2,5"``).
NUMBER_RE = r"\d+[.,]?\d*"

# Generic range patterns reused across nutrition parsing.
PLUS_MINUS_RANGE_RE = re.compile(rf"({NUMBER_RE})\s*±\s*({NUMBER_RE})")
DASH_RANGE_RE = re.compile(rf"({NUMBER_RE})\s*[–-]\s*({NUMBER_RE})")

# Variants of the "XE" keyword (latin/cyrillic).
XE_WORD_RE = re.compile(r"(?:[хx][еe]|xe)", re.IGNORECASE)

# Indicator keywords for ``smart_input``.
SUGAR_WORD_RE = re.compile(r"(?:sugar|сахар)", re.IGNORECASE)
XE_LABEL_RE = re.compile(r"(?:xe|хе)", re.IGNORECASE)
DOSE_WORD_RE = re.compile(r"(?:dose|доза|болюс)", re.IGNORECASE)

# Precompiled patterns built from the bases above.
CARBS_LABELED_PM_RE = re.compile(
    rf"углевод[^\d]*:\s*({NUMBER_RE})\s*(?:г)?\s*±\s*({NUMBER_RE})\s*г",
    re.IGNORECASE,
)
CARBS_LABEL_RE = re.compile(r"углевод[^\d]*:\s*([\d.,]+)\s*г", re.IGNORECASE)
XE_COLON_PM_RE = re.compile(
    rf"\b{XE_WORD_RE.pattern}\s*:\s*{PLUS_MINUS_RANGE_RE.pattern}",
    re.IGNORECASE,
)
XE_COLON_RANGE_RE = re.compile(
    rf"\b{XE_WORD_RE.pattern}\s*:\s*{DASH_RANGE_RE.pattern}",
    re.IGNORECASE,
)
XE_COLON_SINGLE_RE = re.compile(
    rf"\b{XE_WORD_RE.pattern}\s*:\s*([\d.,]+)", re.IGNORECASE
)
XE_PM_RE = re.compile(
    rf"{PLUS_MINUS_RANGE_RE.pattern}\s*{XE_WORD_RE.pattern}",
    re.IGNORECASE,
)
XE_RANGE_RE = re.compile(
    rf"{DASH_RANGE_RE.pattern}\s*{XE_WORD_RE.pattern}",
    re.IGNORECASE,
)
CARBS_PM_RE = re.compile(
    rf"({NUMBER_RE})\s*(?:г)?\s*±\s*({NUMBER_RE})\s*г", re.IGNORECASE
)
CARBS_RANGE_RE = re.compile(
    rf"{DASH_RANGE_RE.pattern}\s*г", re.IGNORECASE
)

# Patterns for ``smart_input``.
BAD_SUGAR_UNIT_RE = re.compile(
    rf"\b{SUGAR_WORD_RE.pattern}\s*[:=]?\s*{NUMBER_RE}\s*(?:xe|хе|ед)\b(?!\s*[\d=:])"
)
BAD_XE_UNIT_RE = re.compile(
    rf"\b{XE_LABEL_RE.pattern}\s*[:=]?\s*{NUMBER_RE}\s*(?:ммоль(?:/л)?|mmol(?:/l)?|ед)\b(?![=:])"
)
BAD_DOSE_UNIT_RE = re.compile(
    rf"\b{DOSE_WORD_RE.pattern}\s*[:=]?\s*{NUMBER_RE}\s*(?:ммоль(?:/л)?|mmol(?:/l)?|xe|хе)\b(?![=:])"
)

SUGAR_VALUE_RE = re.compile(
    rf"\b{SUGAR_WORD_RE.pattern}\s*[:=]?\s*({NUMBER_RE})(?=(?:\s*(?:ммоль/?л|mmol/?l))?\b)"
)
SUGAR_UNIT_RE = re.compile(rf"\b({NUMBER_RE})\s*(ммоль/?л|mmol/?l)\b")
XE_VALUE_RE = re.compile(rf"\b{XE_LABEL_RE.pattern}\s*[:=]?\s*({NUMBER_RE})\b")
XE_UNIT_RE = re.compile(rf"\b({NUMBER_RE})\s*(?:xe|хе)\b")
DOSE_VALUE_RE = re.compile(
    rf"\b{DOSE_WORD_RE.pattern}\s*[:=]?\s*({NUMBER_RE})\b"
)
DOSE_UNIT_RE = re.compile(rf"\b({NUMBER_RE})\s*(?:ед\.?|units?|u)\b")
ONLY_NUMBER_RE = re.compile(rf"\s*({NUMBER_RE})\s*")

EXPLICIT_SUGAR_RE = re.compile(rf"\b{SUGAR_WORD_RE.pattern}\b")
EXPLICIT_XE_RE = re.compile(rf"\b{XE_LABEL_RE.pattern}\b")
EXPLICIT_DOSE_RE = re.compile(rf"\b{DOSE_WORD_RE.pattern}\b")

# Helpers for first-line detection in ``extract_nutrition_info``.
FIRST_LINE_INFO_RE = re.compile(r"\d|углевод|[хx][еe]", re.IGNORECASE)


def _safe_float(value: str) -> float | None:
    """Возвращает число из строки.

    Принимает запятую или точку как разделитель. Если передана не строка
    или число не удаётся распознать, возвращается ``None``.

    Args:
        value: Строка с числом, например ``"1,5"`` или ``"2.0"``.

    Returns:
        Число с плавающей точкой или ``None``.

    Examples:
        >>> _safe_float("1,5")
        1.5
    """
    if not isinstance(value, str):
        return None
    try:
        return float(value.strip().replace(",", "."))
    except ValueError:
        return None


@dataclass
class PatientProfile:
    """Профиль пациента для расчёта болюса.

    Attributes:
        icr: Коэффициент чувствительности к углеводам.
        cf: Коррекционный фактор для сахара крови.
        target_bg: Целевой уровень сахара.
    """

    icr: float
    cf: float
    target_bg: float


def calc_bolus(carbs_g: float, current_bg: float, profile: PatientProfile) -> float:
    """Рассчитывает дозу инсулина по углеводам и сахару.

    Args:
        carbs_g: Количество углеводов в граммах.
        current_bg: Текущий уровень сахара в крови.
        profile: Настройки пациента с коэффициентами.

    Returns:
        Округлённый болюс в единицах инсулина.

    Examples:
        >>> profile = PatientProfile(icr=10, cf=50, target_bg=5.5)
        >>> calc_bolus(60, 7.0, profile)
        6.0
    """
    if profile.icr <= 0:
        raise ValueError("Profile icr must be greater than 0")
    if profile.cf <= 0:
        raise ValueError("Profile cf must be greater than 0")
    if profile.target_bg <= 0:
        raise ValueError("Profile target_bg must be greater than 0")
    if carbs_g < 0:
        raise ValueError("carbs_g must be non-negative")
    if current_bg < 0:
        raise ValueError("current_bg must be non-negative")
    meal = carbs_g / profile.icr
    correction = max(0, (current_bg - profile.target_bg) / profile.cf)
    return round(meal + correction, 1)


def extract_nutrition_info(text: str) -> tuple[float | None, float | None]:
    """Извлекает углеводы и ХЕ из произвольной строки.

    Поддерживаются варианты: ``"углеводы: 30 г"``, ``"XE: 2-3"``,
    ``"2–3 ХЕ"`` и записи с погрешностью ``"a ± b"``.
    Десятичная часть может быть отделена запятой. При указании
    ``"a ± b"`` возвращается центральное значение ``a``, а ``b``
    игнорируется.

    Args:
        text: Строка с описанием продукта или блюда.

    Returns:
        Кортеж ``(carbs, xe)``, где значения могут быть ``None``.

    Examples:
        >>> extract_nutrition_info("углеводы: 30 г, XE: 2")
        (30.0, 2.0)
        >>> extract_nutrition_info("2–3 ХЕ")
        (None, 2.5)
        >>> extract_nutrition_info("углеводы: 45 ± 5 г")
        (45.0, None)
    """
    if not isinstance(text, str):
        return (None, None)
    # Если первая строка не содержит цифр или ключевых слов,
    # считаем её названием блюда и игнорируем
    lines = text.splitlines()
    if len(lines) > 1 and not FIRST_LINE_INFO_RE.search(lines[0]):
        text = "\n".join(lines[1:])

    carbs = xe = None
    # Парсим углеводы (carbs)
    m = CARBS_LABELED_PM_RE.search(text)
    if m:
        first = _safe_float(m.group(1))
        second = _safe_float(m.group(2))
        if first is not None and second is not None:
            # В формате "a ± b" возвращаем центральное значение "a"
            # Погрешность "b" пока игнорируется
            carbs = first
    else:
        m = CARBS_LABEL_RE.search(text)
        if m:
            carbs = _safe_float(m.group(1))
    # Диапазон XE c двоеточием (например XE: 2±1 или XE: 2–3)
    rng = XE_COLON_PM_RE.search(text)
    if rng:
        first = _safe_float(rng.group(1))
        second = _safe_float(rng.group(2))
        if first is not None and second is not None:
            # Возвращаем центральное значение "a" из записи "a ± b"
            xe = first
    else:
        rng = XE_COLON_RANGE_RE.search(text)
        if rng:
            first = _safe_float(rng.group(1))
            second = _safe_float(rng.group(2))
            if first is not None and second is not None:
                xe = (first + second) / 2
        else:
            # Одинарное значение XE: 3.1
            m = XE_COLON_SINGLE_RE.search(text)
            if m:
                xe = _safe_float(m.group(1))
            # Диапазон XE без двоеточия (например 2±1 ХЕ или 2–3 ХЕ)
            if xe is None:
                rng = XE_PM_RE.search(text)
                if rng:
                    first = _safe_float(rng.group(1))
                    second = _safe_float(rng.group(2))
                    if first is not None and second is not None:
                        # Погрешность игнорируется, берём только значение "a"
                        xe = first
            if xe is None:
                rng = XE_RANGE_RE.search(text)
                if rng:
                    first = _safe_float(rng.group(1))
                    second = _safe_float(rng.group(2))
                    if first is not None and second is not None:
                        xe = (first + second) / 2
    # Диапазон углеводов (carbs) если не найдено
    if carbs is None:
        rng = CARBS_PM_RE.search(text)
        if rng:
            first = _safe_float(rng.group(1))
            second = _safe_float(rng.group(2))
            if first is not None and second is not None:
                # Центральное значение при указании "a ± b"
                carbs = first
    if carbs is None:
        rng = CARBS_RANGE_RE.search(text)
        if rng:
            first = _safe_float(rng.group(1))
            second = _safe_float(rng.group(2))
            if first is not None and second is not None:
                carbs = (first + second) / 2
    return carbs, xe


def smart_input(message: str) -> dict[str, float | None]:
    """Парсит сырое сообщение с показателями сахара, ХЕ и дозы инсулина.

    Функция пытается распознать значения сахара крови, хлебных единиц и дозы
    инсулина из произвольного текста. Поддерживаются числовые значения с
    разделителем ``","`` или ``".`` и локализованные термины вроде
    ``"сахар"`` и ``"доза"``. Если после названия показателя указаны
    единицы, не соответствующие ему (например, ``"сахар 7 XE"``), или
    вместо числа идёт произвольный текст (``"доза=abc"``), будет вызван
    ``ValueError``.

    Args:
        message: Исходное сообщение пользователя.

    Returns:
        Словарь с ключами ``"sugar"``, ``"xe"`` и ``"dose"``. Отсутствующие
        значения возвращаются как ``None``.

    Examples:
        >>> smart_input("sugar=7 xe=3 dose=4")
        {'sugar': 7.0, 'xe': 3.0, 'dose': 4.0}
        >>> smart_input("7 ммоль/л, 3 XE")
        {'sugar': 7.0, 'xe': 3.0, 'dose': None}
        >>> smart_input("сахар 7 XE")
        Traceback (most recent call last):
        ...
        ValueError: mismatched unit for sugar
    """

    if not isinstance(message, str):
        raise ValueError("message must be a string")

    text = message.lower()
    result: dict[str, float | None] = {"sugar": None, "xe": None, "dose": None}

    # Проверка на неверные единицы измерения после явных названий показателей
    if BAD_SUGAR_UNIT_RE.search(text):
        raise ValueError("mismatched unit for sugar")
    if BAD_XE_UNIT_RE.search(text):
        raise ValueError("mismatched unit for xe")
    if BAD_DOSE_UNIT_RE.search(text):
        raise ValueError("mismatched unit for dose")

    # --- Sugar ---
    m = SUGAR_VALUE_RE.search(text)
    if m:
        result["sugar"] = _safe_float(m.group(1))
    else:
        m = SUGAR_UNIT_RE.search(text)
        if m:
            result["sugar"] = _safe_float(m.group(1))

    # --- XE ---
    m = XE_VALUE_RE.search(text)
    if m:
        result["xe"] = _safe_float(m.group(1))
    else:
        m = XE_UNIT_RE.search(text)
        if m:
            result["xe"] = _safe_float(m.group(1))

    # --- Dose ---
    m = DOSE_VALUE_RE.search(text)
    if m:
        result["dose"] = _safe_float(m.group(1))
    else:
        m = DOSE_UNIT_RE.search(text)
        if m:
            result["dose"] = _safe_float(m.group(1))

    if all(v is None for v in result.values()):
        m = ONLY_NUMBER_RE.fullmatch(text)
        if m:
            result["sugar"] = _safe_float(m.group(1))

    # Явное упоминание показателя без числового значения считается ошибкой.
    for key, pattern in [
        ("sugar", EXPLICIT_SUGAR_RE),
        ("xe", EXPLICIT_XE_RE),
        ("dose", EXPLICIT_DOSE_RE),
    ]:
        if pattern.search(text) and result[key] is None:
            raise ValueError(f"invalid number for {key}")

    return result
