from services.gemini import generate_text
import json, re

async def generate_funnel_content(title: str, audience: str, description: str, cta_text: str) -> dict:
    prompt = f"""Generate a landing page for Brandon Sweeney's real estate business.

Details:
- Title: {title}
- Audience: {audience}
- Description: {description}
- CTA: {cta_text}

Brandon Sweeney is the 2025 NEAR REALTOR® Of The Year, CEO of Sold With Sweeney & Co., Keller Williams Realty Success.

Generate structured content sections in JSON:
{{
  "hero_headline": "...",
  "hero_subtext": "...",
  "details_heading": "...",
  "details_body": "...",
  "value_props": ["...", "...", "..."],
  "testimonial": "...",
  "cta_headline": "...",
  "cta_subtext": "..."
}}"""
    text = await generate_text(prompt, use_pro=True)
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        return json.loads(match.group())
    return {"hero_headline": title, "hero_subtext": description, "value_props": [], "cta_headline": cta_text, "cta_subtext": ""}
