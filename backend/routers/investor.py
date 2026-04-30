import json
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.analytics_event import AnalyticsEvent
from models.lead import Lead
from services.notification_service import enqueue_notification, run_notification_retry_pass
from services.investor_service import generate_investor_analysis
from services.rentcast_service import get_full_property_data

router = APIRouter()


class InvestorInputs(BaseModel):
    # Property
    address: Optional[str] = None
    property_type: str = "single_family"
    units: int = 1
    # Financials
    purchase_price: float
    down_payment_pct: float = 20.0
    interest_rate: float = 7.0
    loan_term_years: int = 30
    monthly_rent_total: float
    rehab_costs: float = 0
    annual_taxes: float = 0
    annual_insurance: float = 0
    monthly_maintenance: float = 0
    vacancy_rate_pct: float = 5.0
    mgmt_fee_pct: float = 0.0
    hold_years: int = 5
    appreciation_rate_pct: float = 3.0
    # Lead
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


def calculate_metrics(inp: InvestorInputs) -> dict:
    loan_amount = inp.purchase_price * (1 - inp.down_payment_pct / 100)
    down_payment = inp.purchase_price * (inp.down_payment_pct / 100)
    monthly_rate = inp.interest_rate / 100 / 12
    loan_term_months = max(inp.loan_term_years * 12, 1)
    is_short_term_investor_debt = inp.loan_term_years <= 2
    if is_short_term_investor_debt:
        mortgage = loan_amount * monthly_rate
        loan_structure = "interest_only"
    elif monthly_rate > 0:
        n = loan_term_months
        mortgage = loan_amount * (monthly_rate * (1 + monthly_rate)**n) / ((1 + monthly_rate)**n - 1)
        loan_structure = "amortized"
    else:
        mortgage = loan_amount / loan_term_months
        loan_structure = "amortized"

    gross_rent = inp.monthly_rent_total
    vacancy_loss = gross_rent * (inp.vacancy_rate_pct / 100)
    effective_rent = gross_rent - vacancy_loss
    mgmt_fee = effective_rent * (inp.mgmt_fee_pct / 100)
    monthly_tax = inp.annual_taxes / 12
    monthly_insurance = inp.annual_insurance / 12
    total_expenses = mgmt_fee + monthly_tax + monthly_insurance + inp.monthly_maintenance
    noi = effective_rent - total_expenses
    cash_flow = noi - mortgage
    total_cash_required = down_payment + inp.rehab_costs + (inp.purchase_price * 0.03)
    cap_rate = (noi * 12) / inp.purchase_price * 100 if inp.purchase_price > 0 else 0
    coc = (cash_flow * 12) / total_cash_required * 100 if total_cash_required > 0 else 0

    return {
        "monthly_gross_rent": round(gross_rent, 2),
        "monthly_mortgage": round(mortgage, 2),
        "monthly_noi": round(noi, 2),
        "monthly_cash_flow": round(cash_flow, 2),
        "cap_rate_pct": round(cap_rate, 2),
        "cash_on_cash_pct": round(coc, 2),
        "total_cash_required": round(total_cash_required, 2),
        "down_payment": round(down_payment, 2),
        "loan_amount": round(loan_amount, 2),
        "loan_structure": loan_structure,
    }


@router.post("/calculate")
async def calculate(inp: InvestorInputs):
    metrics = calculate_metrics(inp)
    return {"metrics": metrics}


@router.post("/analyze")
async def full_analysis(inp: InvestorInputs, db: AsyncSession = Depends(get_db)):
    """Full AI analysis — email required for lead capture."""
    if not inp.email:
        raise HTTPException(status_code=422, detail="email is required for analysis")
    metrics = calculate_metrics(inp)
    lead_meta = json.dumps({"purchase_price": inp.purchase_price, "property_type": inp.property_type, "address": inp.address})
    lead = Lead(
        name=inp.name or "", email=inp.email, phone=inp.phone,
        source="investor_tool", lead_type="investor",
        metadata_json=lead_meta,
    )
    db.add(lead)
    await db.flush()
    await enqueue_notification(
        db,
        event_type="investor_report_requested",
        payload={
            "address": inp.address,
            "property_type": inp.property_type,
            "purchase_price": inp.purchase_price,
            "down_payment_pct": inp.down_payment_pct,
            "interest_rate": inp.interest_rate,
            "hold_years": inp.hold_years,
            "monthly_rent_total": inp.monthly_rent_total,
            "rehab_costs": inp.rehab_costs,
            "name": inp.name,
            "email": inp.email,
            "phone": inp.phone,
        },
    )
    await db.commit()
    await run_notification_retry_pass(limit=5)
    ai_report = await generate_investor_analysis(inp.model_dump(), metrics)
    return {"metrics": metrics, "report": ai_report}


@router.post("/engagement")
async def track_engagement(
    session_key: str = Body(...),
    purchase_price: float = Body(...),
    rehab_costs: float = Body(...),
    arv: float = Body(...),
    hold_months: int = Body(...),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(AnalyticsEvent).where(
            AnalyticsEvent.event_type == "investor_calculator_engaged",
            AnalyticsEvent.metadata_json.contains(session_key),
        )
    )
    if existing.scalar_one_or_none():
        return {"queued": False}

    event = AnalyticsEvent(
        event_type="investor_calculator_engaged",
        page="/invest",
        referrer=None,
        user_agent=None,
        device_type=None,
        metadata_json=json.dumps(
            {
                "session_key": session_key,
                "purchase_price": purchase_price,
                "rehab_costs": rehab_costs,
                "arv": arv,
                "hold_months": hold_months,
            },
            separators=(",", ":"),
        ),
    )
    db.add(event)
    await db.flush()
    await enqueue_notification(
        db,
        event_type="investor_calculator_engaged",
        payload={
            "session_key": session_key,
            "purchase_price": purchase_price,
            "rehab_costs": rehab_costs,
            "arv": arv,
            "hold_months": hold_months,
        },
    )
    await db.commit()
    await run_notification_retry_pass(limit=5)
    return {"queued": True}


class LookupRequest(BaseModel):
    address: str


@router.post("/lookup")
async def lookup_property(req: LookupRequest):
    """Fetch property data from RentCast to auto-fill investor calculator fields."""
    if not req.address or len(req.address.strip()) < 5:
        raise HTTPException(status_code=422, detail="A valid property address is required.")

    data = await get_full_property_data(req.address.strip())

    if data["data_source"] == "none":
        raise HTTPException(status_code=404, detail="Property not found. Try entering the full street address, city, state, and ZIP.")

    prop = data["property_record"] or {}
    value = data["value_estimate"] or {}
    rent = data["rent_estimate"] or {}
    subject = value.get("subjectProperty", {})

    # Extract the most recent tax assessment
    tax_assessments = prop.get("taxAssessments", {})
    property_taxes = prop.get("propertyTaxes", {})
    latest_tax_year = max(property_taxes.keys()) if property_taxes else None
    annual_taxes = property_taxes.get(latest_tax_year, {}).get("total", 0) if latest_tax_year else 0

    # Estimate insurance from value (~0.5% of AVM)
    avm_price = value.get("price", 0)
    estimated_insurance = round(avm_price * 0.005) if avm_price else 0

    # Format comparable sales
    sale_comps = []
    for comp in value.get("comparables", [])[:5]:
        sale_comps.append({
            "address": comp.get("formattedAddress", ""),
            "price": comp.get("price"),
            "bedrooms": comp.get("bedrooms"),
            "bathrooms": comp.get("bathrooms"),
            "sqft": comp.get("squareFootage"),
            "distance_miles": round(comp.get("distance", 0), 2),
            "correlation": round(comp.get("correlation", 0), 4),
        })

    return {
        "address": subject.get("formattedAddress") or prop.get("formattedAddress") or req.address,
        "property_type": subject.get("propertyType") or prop.get("propertyType", "Single Family"),
        "bedrooms": subject.get("bedrooms") or prop.get("bedrooms"),
        "bathrooms": subject.get("bathrooms") or prop.get("bathrooms"),
        "sqft": subject.get("squareFootage") or prop.get("squareFootage"),
        "year_built": subject.get("yearBuilt") or prop.get("yearBuilt"),
        "lot_size": prop.get("lotSize"),
        "purchase_price": avm_price,
        "price_range_low": value.get("priceRangeLow"),
        "price_range_high": value.get("priceRangeHigh"),
        "monthly_rent": rent.get("rent"),
        "rent_range_low": rent.get("rentRangeLow"),
        "rent_range_high": rent.get("rentRangeHigh"),
        "annual_taxes": annual_taxes,
        "estimated_insurance": estimated_insurance,
        "last_sale_date": subject.get("lastSaleDate") or prop.get("lastSaleDate"),
        "last_sale_price": subject.get("lastSalePrice") or prop.get("lastSalePrice"),
        "comparables": sale_comps,
        "data_source": "rentcast",
    }
