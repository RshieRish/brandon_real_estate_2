from services.gemini import generate_text
import httpx


async def geocode_address(address: str) -> dict:
    """Basic geocode using Nominatim (free)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address, "format": "json", "limit": 1},
            headers={"User-Agent": "SoldWithSweeney/1.0"}
        )
        results = resp.json()
        if results:
            return {"lat": results[0]["lat"], "lon": results[0]["lon"], "display": results[0]["display_name"]}
    return {}


async def evaluate_property(data: dict) -> dict:
    prompt = f"""You are a real estate valuation assistant for Brandon Sweeney, REALTOR® in MA/NH.

A seller has provided the following property details:
- Address: {data.get('address', 'Unknown')}
- Property type: {data.get('property_type', 'Unknown')}
- Bedrooms: {data.get('bedrooms', 'Unknown')}
- Bathrooms: {data.get('bathrooms', 'Unknown')}
- Square footage: {data.get('sqft', 'Unknown')}
- Year built: {data.get('year_built', 'Unknown')}
- Condition: {data.get('condition', 'Unknown')}
- Recent upgrades: {data.get('upgrades', 'None')}

Based on general MA/NH market knowledge for the Merrimack Valley region, provide:
1. An estimated value range (e.g. "$450,000 – $490,000")
2. Confidence level: Low, Medium, or High
3. A 2-3 sentence plain-English explanation of what's driving the estimate
4. 3-4 key factors affecting value

Respond in this exact JSON format:
{{
  "range_low": 450000,
  "range_high": 490000,
  "confidence": "Medium",
  "explanation": "...",
  "key_factors": ["...", "...", "..."]
}}

Important: This is an AI estimate, not a formal appraisal. Be conservative and honest about uncertainty."""

    text = await generate_text(prompt, use_pro=True)
    import re, json
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        return json.loads(match.group())
    return {"range_low": 0, "range_high": 0, "confidence": "Low", "explanation": "Unable to generate estimate.", "key_factors": []}
