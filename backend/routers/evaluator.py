from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
import json
from database import get_db
from models.lead import Lead
from services.evaluator_service import evaluate_property, geocode_address

router = APIRouter()


class EvaluatorRequest(BaseModel):
    address: Optional[str] = None
    property_type: str
    bedrooms: int
    bathrooms: float
    sqft: Optional[int] = None
    year_built: Optional[int] = None
    condition: str
    upgrades: Optional[List[str]] = None
    # Lead capture
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


@router.post("/")
async def evaluate(req: EvaluatorRequest, db: AsyncSession = Depends(get_db)):
    data = req.model_dump()

    # Capture lead if contact info provided
    if req.email:
        property_meta = {k: data[k] for k in ["property_type", "bedrooms", "bathrooms", "sqft", "year_built", "condition", "upgrades"] if k in data}
        lead = Lead(name=req.name or "", email=req.email, phone=req.phone, source="evaluator", lead_type="seller", metadata_json=json.dumps(property_meta))
        db.add(lead)

    geo = {}
    if req.address:
        geo = await geocode_address(req.address)

    try:
        result = await evaluate_property(data)
    except Exception as e:
        err = str(e)
        if "quota" in err.lower() or "429" in err or "ResourceExhausted" in err:
            raise HTTPException(status_code=503, detail="AI valuation service temporarily unavailable. Please try again later.")
        raise HTTPException(status_code=502, detail="AI service error.")

    # Normalize field names — service returns range_low/range_high, frontend expects price_low/price_high
    result["price_low"] = result.pop("range_low", result.get("price_low", 0))
    result["price_high"] = result.pop("range_high", result.get("price_high", 0))
    result["address"] = geo.get("display", req.address)
    result["disclaimer"] = "This is an AI-assisted estimate, not a formal appraisal. For an accurate valuation, book a meeting with Brandon."
    return result
