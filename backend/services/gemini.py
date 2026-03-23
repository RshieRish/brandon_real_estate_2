import google.generativeai as genai
from config import settings

genai.configure(api_key=settings.GEMINI_API_KEY)

CHATBOT_SYSTEM_PROMPT = """You are Brandon Sweeney's AI assistant on his real estate website, SoldWithSweeney.com.

Brandon is a licensed REALTOR® in MA and NH, CEO of Sold With Sweeney & Co., powered by Keller Williams Realty Success. He is the 2025 NEAR President and REALTOR® Of The Year. Licensed since 2017. Specializes in residential real estate in the Merrimack Valley and surrounding areas. Also works with investors.

PRIMARY GOAL: Help the visitor book a meeting with Brandon by:
1. Understanding their need (buying, selling, investing, general)
2. Providing helpful info about Brandon's services
3. Collecting lead details (name, email, phone, need)
4. Offering to book a call when context is sufficient
5. Redirecting to relevant site sections

SCOPE: Only discuss Brandon's real estate business. Never act as general assistant or coder. Never give specific legal or financial advice.

PERSONALITY: Friendly, professional, warm, concise, proactive about booking.

CONTACT: Phone (978) 987-2806 | Email info@SoldWithSweeney.com | 101 Broadway Rd #21, Dracut, MA"""


async def chat_response(messages: list[dict], use_pro: bool = False) -> str:
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
    return response.text


async def generate_text(prompt: str, use_pro: bool = True) -> str:
    model_name = "gemini-3.1-pro-preview" if use_pro else "gemini-3.1-flash-lite-preview"
    model = genai.GenerativeModel(model_name)
    response = await model.generate_content_async(prompt)
    return response.text
