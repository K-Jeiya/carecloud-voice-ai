"""Optional SYNTHETIC demo data. Run:  python -m app.seed   (or set SEED_DEMO_DATA=true)."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app import crud
from app.database import SessionLocal, init_db
from app.schemas import PatientCreate

logger = logging.getLogger("carecloud.seed")

# Obviously fake: 555-01xx numbers are reserved for fiction, last name "Synthetic".
SYNTHETIC_PATIENTS = [
    dict(first_name="Jane", last_name="Synthetic", date_of_birth="1985-04-12", sex="Female",
         phone_number="2025550101", email="jane.synthetic@example.com",
         address_line_1="100 Demo Street", city="Springfield", state="IL", zip_code="62701"),
    dict(first_name="John", last_name="Synthetic", date_of_birth="1972-11-03", sex="Male",
         phone_number="2025550102", address_line_1="200 Sample Avenue", address_line_2="Apt 4",
         city="Portland", state="OR", zip_code="97201", insurance_provider="Demo Health Plan",
         insurance_member_id="DEMO12345"),
]


def seed_demo_data(db: Session) -> int:
    created = 0
    for raw in SYNTHETIC_PATIENTS:
        data = PatientCreate(**raw)
        if crud.find_active_by_phone(db, data.phone_number) is None:
            crud.create(db, data.model_dump())
            created += 1
    logger.info("Seeded %d synthetic demo patient(s)", created)
    return created


if __name__ == "__main__":
    init_db()
    with SessionLocal() as session:
        print(f"Created {seed_demo_data(session)} synthetic patient(s).")
