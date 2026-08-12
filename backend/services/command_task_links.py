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


def task_link_display_name(entity_type: str, record) -> str:
    if entity_type == "contact":
        return f"{record.first_name} {record.last_name}".strip()
    if entity_type == "listing":
        return record.address
    return record.title if entity_type == "agreement" else record.name
