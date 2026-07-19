"""Turn a free-form transcript into structured expense rows using a Groq LLM."""

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from string import Template
from zoneinfo import ZoneInfo

from groq import AsyncGroq

from config import BOT_TIMEZONE, CATEGORIES, GROQ_API_KEY, GROQ_LLM_MODEL

log = logging.getLogger(__name__)

_client = AsyncGroq(api_key=GROQ_API_KEY)

# Uses string.Template ($name) rather than str.format, because the prompt is full of
# literal JSON braces that .format would try to interpret as placeholders.
SYSTEM_PROMPT = Template("""You extract expenses from a short spoken message. The \
speaker may use English, Russian, or Spanish — handle any of them.

Reply with JSON only, shaped exactly like:
{"expenses": [{"amount": 15.0, "currency": "USD", "category": "food", \
"note": "lunch", "date": "$today"}]}

Rules:
- One object per distinct expense. "15 on lunch and 30 on gas" is two objects.
- amount: a positive number. Spoken forms count: "fifteen bucks" -> 15, \
"полторы тысячи" -> 1500, "dos cincuenta" -> 2.50 or 250 by context.
- currency: ISO code (USD, EUR, RUB, GBP...). Use "$default_currency" when the \
speaker names no currency.
- category: exactly one of $categories. Pick the closest; use "other" only as a \
last resort.
- note: a short description in the speaker's own words, max 5 words.
- date: YYYY-MM-DD. Today is $today. Resolve "yesterday"/"вчера"/"ayer" and \
weekday references relative to that. Use today when unstated.
- If the message contains no expense at all, reply {"expenses": []}.
""")


@dataclass
class ParsedExpense:
    amount: Decimal
    currency: str
    category: str
    note: str
    spent_on: date


async def parse_expenses(text: str, default_currency: str) -> list[ParsedExpense]:
    """Extract zero or more expenses from a transcript. Never raises on bad LLM output."""
    today = datetime.now(ZoneInfo(BOT_TIMEZONE)).date()
    system = SYSTEM_PROMPT.substitute(
        default_currency=default_currency,
        categories=", ".join(CATEGORIES),
        today=today.isoformat(),
    )

    completion = await _client.chat.completions.create(
        model=GROQ_LLM_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
    )
    raw = completion.choices[0].message.content
    log.info("parsed %r -> %s", text, raw)

    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        log.warning("LLM returned non-JSON: %r", raw)
        return []

    out = []
    for item in payload.get("expenses") or []:
        parsed = _coerce(item, default_currency, today)
        if parsed:
            out.append(parsed)
    return out


def _coerce(item: dict, default_currency: str, today: date) -> ParsedExpense | None:
    """Validate one LLM-produced object, dropping anything unusable."""
    if not isinstance(item, dict):
        return None

    try:
        amount = Decimal(str(item.get("amount"))).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if amount <= 0:
        return None

    currency = str(item.get("currency") or default_currency).upper()[:3]

    category = str(item.get("category") or "other").lower()
    if category not in CATEGORIES:
        category = "other"

    note = (str(item.get("note") or "") or category).strip()[:100]

    spent_on = today
    if raw_date := item.get("date"):
        try:
            spent_on = date.fromisoformat(str(raw_date))
        except ValueError:
            pass
        # Guard against the model hallucinating a far-future date.
        if spent_on > today + timedelta(days=1):
            spent_on = today

    return ParsedExpense(amount, currency, category, note, spent_on)
