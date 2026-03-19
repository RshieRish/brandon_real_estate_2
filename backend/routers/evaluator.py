from fastapi import APIRouter, Depends
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

    result = await evaluate_property(data)
    result["address_display"] = geo.get("display", req.address)
    result["coordinates"] = {"lat": geo.get("lat"), "lon": geo.get("lon")}
    result["disclaimer"] = "This is an AI-assisted estimate, not a formal appraisal. For an accurate valuation, book a meeting with Brandon."
    return result
