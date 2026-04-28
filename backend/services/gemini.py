import json
import re
from typing import Any

import google.generativeai as genai
from config import settings

genai.configure(api_key=settings.GEMINI_API_KEY)

CHATBOT_SYSTEM_PROMPT = """You are Brandon Sweeney's AI assistant on his real estate website, SoldWithSweeney.com.

Brandon is a licensed real estate agent in MA and NH, CEO of Sold With Sweeney & Co., powered by Keller Williams Realty Success. He is a REALTOR® (member of the National Association of REALTORS®), the 2025 NEAR President, and REALTOR® Of The Year. Licensed since 2017. Specializes in residential real estate across Northern Massachusetts and Southern New Hampshire. Also works with investors.

PRIMARY GOAL: Help the visitor book a meeting with Brandon by:
1. Understanding their need (buying, selling, investing, general)
2. Providing helpful info about Brandon's services
3. Collecting lead details (name, email, phone, need)
4. Offering to book a call when context is sufficient
5. Redirecting to relevant site sections

SCOPE: Only discuss Brandon's real estate business. Never act as general assistant or coder. Never give specific legal or financial advice.

CRITICAL RULES:
- When describing Brandon's qualifications, always say "licensed real estate agent" — NOT "licensed REALTOR®". REALTOR® is a membership mark, not a license. You may refer to him as a REALTOR® only when talking about his membership or awards (e.g. "REALTOR® Of The Year").
- NEVER mention "current listings", "view listings", "browse listings", or suggest any listings page. This website does not have a listings feature. Instead, offer to book a call with Brandon to discuss available properties.
- When referring to the area Brandon serves, say "Northern Massachusetts and Southern New Hampshire" — NOT "Merrimack Valley".

PERSONALITY: Friendly, professional, warm, concise, proactive about booking.

CONTACT: Phone (978) 987-2806 | Email info@soldwithsweeney.com | 101 Broadway Rd #21, Dracut, MA

RESPONSE FORMAT:
Return ONLY valid JSON with this exact shape:
{
  "text": "Short, warm reply here.",
  "actions": [],
  "widget": null
}

ACTION TYPES:
- send_message: { "type": "send_message", "label": "Buy a home", "message": "I want help buying a home in MA/NH" }
- navigate: { "type": "navigate", "label": "See buyer experience", "href": "/buy" }
- open_widget: { "type": "open_widget", "label": "Book a call", "widget": "calendar_picker" }

RESPONSE RULES:
- Do not use markdown fences or any text outside the JSON object.
- Keep `text` concise and natural.
- When you offer 2 or more next-step options, put them in `actions` instead of listing them in `text`.
- Use at most 4 actions.
- When the visitor is ready to book, set `widget` to "calendar_picker".
- Do not use legacy bracket tags like [BOOK_MEETING].
- Only use these routes for `navigate`: /buy, /sell, /invest, /about
- If no actions are needed, return an empty array.
"""

BOOKING_TRIGGERS = (
    "[BOOK_MEETING]",
    "[BOOKING]",
    "[CALENDAR]",
)

ALLOWED_ROUTES = {"/buy", "/sell", "/invest", "/about"}
DISCOVERY_ACTIONS = [
    {
        "type": "send_message",
        "label": "Buy a home",
        "message": "I want help buying a home in MA/NH",
    },
    {
        "type": "send_message",
        "label": "Sell my home",
        "message": "I want help selling my home in MA/NH",
    },
    {
        "type": "send_message",
        "label": "Review investments",
        "message": "I want help with real estate investing in MA/NH",
    },
    {
        "type": "open_widget",
        "label": "Book a call",
        "widget": "calendar_picker",
    },
]


def _strip_code_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


def _extract_json_object(raw: str) -> str | None:
    text = _strip_code_fences(raw)
    if text.startswith("{") and text.endswith("}"):
        return text
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else None


def _normalize_widget(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"calendar_picker", "calendar", "booking"}:
        return "calendar_picker"
    return None


def _clean_legacy_booking_tags(text: str) -> tuple[str, bool]:
    cleaned = text
    has_booking_trigger = False
    for trigger in BOOKING_TRIGGERS:
        if trigger in cleaned:
            cleaned = cleaned.replace(trigger, "").strip()
            has_booking_trigger = True
    return cleaned, has_booking_trigger


def _normalize_action(raw_action: Any) -> dict[str, Any] | None:
    if not isinstance(raw_action, dict):
        return None

    action_type = str(raw_action.get("type", "")).strip()
    label = str(raw_action.get("label", "")).strip()
    if not action_type or not label:
        return None

    if action_type == "send_message":
        message = str(raw_action.get("message", "")).strip()
        if not message:
            return None
        return {
            "type": "send_message",
            "label": label[:40],
            "message": message[:280],
        }

    if action_type == "navigate":
        href = str(raw_action.get("href", "")).strip()
        if href not in ALLOWED_ROUTES:
            return None
        return {
            "type": "navigate",
            "label": label[:40],
            "href": href,
        }

    if action_type == "open_widget":
        widget = _normalize_widget(raw_action.get("widget"))
        if widget is None:
            return None
        return {
            "type": "open_widget",
            "label": label[:40],
            "widget": widget,
        }

    return None


def _should_offer_discovery_actions(
    last_user_message: str,
    text: str,
    actions: list[dict[str, Any]],
    widget: str | None,
) -> bool:
    if actions or widget == "calendar_picker":
        return False

    haystack = f"{last_user_message} {text}".lower()
    broad_prompts = (
        "what can you help",
        "how can you help",
        "what do you do",
        "what can i do",
        "what are my options",
        "where should i start",
        "help me choose",
        "buy sell or invest",
    )
    keyword_hits = sum(keyword in haystack for keyword in ("buy", "sell", "invest"))
    return any(prompt in haystack for prompt in broad_prompts) or keyword_hits >= 2


def _parse_chat_response(raw_text: str, last_user_message: str) -> dict[str, Any]:
    parsed_payload: dict[str, Any] = {}
    json_candidate = _extract_json_object(raw_text)
    if json_candidate:
        try:
            maybe_payload = json.loads(json_candidate)
            if isinstance(maybe_payload, dict):
                parsed_payload = maybe_payload
        except json.JSONDecodeError:
            parsed_payload = {}

    text_source = parsed_payload.get("text") if parsed_payload else raw_text
    cleaned_text, has_legacy_booking_trigger = _clean_legacy_booking_tags(str(text_source or raw_text))

    widget = _normalize_widget(parsed_payload.get("widget"))
    if widget is None and has_legacy_booking_trigger:
        widget = "calendar_picker"

    raw_actions = parsed_payload.get("actions", [])
    actions: list[dict[str, Any]] = []
    if isinstance(raw_actions, list):
        for raw_action in raw_actions:
            normalized_action = _normalize_action(raw_action)
            if normalized_action is not None:
                actions.append(normalized_action)

    if _should_offer_discovery_actions(last_user_message, cleaned_text, actions, widget):
        actions = DISCOVERY_ACTIONS.copy()

    if widget == "calendar_picker" and not cleaned_text:
        cleaned_text = "I can pull up Brandon's availability right here."

    if not cleaned_text:
        cleaned_text = "I can help you with that."

    return {
        "text": cleaned_text,
        "actions": actions[:4],
        "widget": widget,
    }


async def chat_response(messages: list[dict], use_pro: bool = False) -> dict[str, Any]:
    model_name = "gemini-3.1-pro-preview" if use_pro else "gemini-3.1-flash-lite-preview"
    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=CHATBOT_SYSTEM_PROMPT,
    )
    history = []
    for msg in messages[:-1]:
        history.append({"role": msg["role"], "parts": [msg["content"]]})
    chat = model.start_chat(history=history)
    response = await chat.send_message_async(messages[-1]["content"])
    return _parse_chat_response(response.text, messages[-1]["content"])


async def generate_text(prompt: str, use_pro: bool = True) -> str:
    model_name = "gemini-3.1-pro-preview" if use_pro else "gemini-3.1-flash-lite-preview"
    model = genai.GenerativeModel(model_name)
    response = await model.generate_content_async(prompt)
    return response.text
