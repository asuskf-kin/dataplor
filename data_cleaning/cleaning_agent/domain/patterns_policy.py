"""When a country's chain patterns must be created or refreshed (user rule)."""

from datetime import date

from pydantic import BaseModel

MAX_AGE_DAYS = 183  # ~6 months


class PatternsStatus(BaseModel):
    country: str
    path: str
    exists: bool
    updated: str | None = None  # yyyy-mm-dd
    source: str | None = None  # "PATTERNS_UPDATED" or "git"


def needs_update(status: PatternsStatus, today: date) -> tuple[bool, str]:
    """(must create/update?, reason in Spanish for the person)."""
    if not status.exists:
        return True, f"No existen patrones para '{status.country}': hay que crearlos"
    if status.updated is None:
        return (
            True,
            "No se sabe cuándo se actualizaron por última vez: hay que revisarlos",
        )
    age = (today - date.fromisoformat(status.updated)).days
    if age > MAX_AGE_DAYS:
        return (
            True,
            f"Última actualización {status.updated} (hace {age} días, más de 6 meses)",
        )
    return False, f"Actualizados el {status.updated} (hace {age} días)"
