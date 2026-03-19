from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models.lead import Lead
from services.investor_service import generate_investor_analysis

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
    n = inp.loan_term_years * 12
    if monthly_rate > 0:
        mortgage = loan_amount * (monthly_rate * (1 + monthly_rate)**n) / ((1 + monthly_rate)**n - 1)
    else:
        mortgage = loan_amount / n

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
    }


@router.post("/calculate")
async def calculate(inp: InvestorInputs):
    metrics = calculate_metrics(inp)
    return {"metrics": metrics}


@router.post("/analyze")
async def full_analysis(inp: InvestorInputs, db: AsyncSession = Depends(get_db)):
    """Full AI analysis — requires lead capture (email required)."""
    metrics = calculate_metrics(inp)
    if inp.email:
        lead = Lead(
            name=inp.name or "", email=inp.email, phone=inp.phone,
            source="investor_tool", lead_type="investor",
            metadata_json="{}"
        )
        db.add(lead)
    ai_report = await generate_investor_analysis(inp.model_dump(), metrics)
    return {"metrics": metrics, "report": ai_report}
