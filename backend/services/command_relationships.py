"""Identity rules for internal Command relationships."""


def is_same_opportunity_contact(
    existing_contact_id: int,
    existing_role: str,
    requested_contact_id: int,
    requested_role: str,
) -> bool:
    return existing_contact_id == requested_contact_id and existing_role == requested_role
