import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Literal
from sqlalchemy.ext.asyncio import AsyncSession
import json
from database import get_db
from models.analytics_event import AnalyticsEvent
from models.lead import Lead
from services.notification_service import enqueue_notification, run_notification_retry_pass
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


class RatingRequest(BaseModel):
    rating: Literal["under", "expected", "above"]


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
        result = await evaluate_property(data, geo=geo)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Valuation service error.") from exc

    # Normalize field names — service returns range_low/range_high, frontend expects price_low/price_high
    result["price_low"] = result.pop("range_low", result.get("price_low", 0))
    result["price_high"] = result.pop("range_high", result.get("price_high", 0))
    result["address"] = geo.get("display", req.address)
    result["disclaimer"] = "This is a market-based estimate, not a formal appraisal. For a true listing price strategy, book a valuation meeting with Brandon."
    calculation_event = AnalyticsEvent(
        event_type="seller_evaluator_calculation",
        page="/sell",
        referrer=None,
        user_agent=None,
        device_type=None,
        metadata_json=json.dumps(
            {
                "inputs": data,
                "result": result,
            }
        ),
    )
    db.add(calculation_event)
    await db.flush()
    await enqueue_notification(
        db,
        event_type="seller_evaluator_calculated",
        payload={
            "address": result["address"],
            "property_type": req.property_type,
            "bedrooms": req.bedrooms,
            "bathrooms": req.bathrooms,
            "sqft": req.sqft,
            "year_built": req.year_built,
            "condition": req.condition,
            "upgrades": req.upgrades or [],
            "price_low": result["price_low"],
            "price_high": result["price_high"],
            "confidence": result["confidence"],
            "name": req.name,
            "email": req.email,
            "phone": req.phone,
        },
    )
    await db.commit()
    # Fire-and-forget: don't block response waiting for email delivery
    asyncio.create_task(run_notification_retry_pass(limit=5))
    result["calculation_id"] = calculation_event.id
    return result


@router.post("/{calculation_id}/rating")
async def submit_rating(
    calculation_id: int,
    payload: RatingRequest,
    db: AsyncSession = Depends(get_db),
):
    calculation = await db.get(AnalyticsEvent, calculation_id)
    if not calculation or calculation.event_type != "seller_evaluator_calculation":
        raise HTTPException(status_code=404, detail="Calculation not found.")

    rating_event = AnalyticsEvent(
        event_type="seller_evaluator_rating",
        page="/sell",
        referrer=None,
        user_agent=None,
        device_type=None,
        metadata_json=json.dumps(
            {
                "calculation_id": calculation_id,
                "rating": payload.rating,
            }
        ),
    )
    db.add(rating_event)
    await db.flush()
    await enqueue_notification(
        db,
        event_type="seller_evaluator_rated",
        payload={
            "calculation_id": calculation_id,
            "rating": payload.rating,
        },
    )
    await db.commit()
    asyncio.create_task(run_notification_retry_pass(limit=5))
    return {"ok": True}
