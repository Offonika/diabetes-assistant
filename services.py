from telegram import InlineKeyboardButton, InlineKeyboardMarkup

PROTOCOLS = {
    "диабет 2 типа": "standard protocol",
    "диабет 1 типа": "insulin protocol",
}

# Base URL for purchases on the partner AgroStore website
AGROSTORE_URL = "https://agrostore.example.com/buy"

def find_protocol_by_diagnosis(diagnosis: str) -> str | None:
    diagnosis = diagnosis.lower()
    return PROTOCOLS.get(diagnosis)


def build_agrostore_deeplink(product_id: str, user_id: int,
                             utm_source: str = "diabetes_bot",
                             utm_medium: str = "telegram",
                             utm_campaign: str = "protocol") -> str:
    """Return deep link URL for AgroStore purchases."""
    params = (
        f"product_id={product_id}",
        f"user_id={user_id}",
        f"utm_source={utm_source}",
        f"utm_medium={utm_medium}",
        f"utm_campaign={utm_campaign}",
    )
    return f"{AGROSTORE_URL}?" + "&".join(params)


def build_protocol_card(protocol: str, product_id: str, user_id: int):
    """Return text and inline keyboard for protocol card."""
    link = build_agrostore_deeplink(product_id, user_id)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Купить", url=link)]])
    return f"📄 {protocol}", kb

