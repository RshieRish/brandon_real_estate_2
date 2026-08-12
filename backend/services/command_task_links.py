"""Internal entity validation for generic task links."""

from models.command import CRMAgreement, CRMContact, CRMListingRecord, CRMOpportunity


_ENTITY_MODELS = {
    "agreement": CRMAgreement,
    "contact": CRMContact,
    "listing": CRMListingRecord,
    "opportunity": CRMOpportunity,
}


def task_link_model(entity_type: str):
    return _ENTITY_MODELS.get(entity_type)
