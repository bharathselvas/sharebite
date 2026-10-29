from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

STATUSES = ("available", "claimed", "picked_up", "cancelled", "expired")
DEMO_DONORS = {"donor-demo", "donor-demo-2"}
DEMO_NGOS = {"ngo-demo", "ngo-demo-2"}
DEMO_ADMIN = "admin-demo"


class DonationFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    food_name: str = Field(min_length=2, max_length=100)
    description: str = Field(default="", max_length=500)
    category: str = Field(default="other", min_length=2, max_length=40)
    quantity: float = Field(gt=0, le=100_000)
    unit: str = Field(min_length=1, max_length=30)
    available_at: datetime | None = None
    pickup_deadline: datetime
    pickup_location: str = Field(default="", max_length=160)

    @field_validator("food_name", "unit", "category")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("pickup_deadline")
    @classmethod
    def normalize_deadline(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("pickup_deadline must include a timezone")
        value = value.astimezone(timezone.utc)
        if value <= datetime.now(timezone.utc):
            raise ValueError("pickup_deadline must be in the future")
        return value

    @field_validator("available_at")
    @classmethod
    def normalize_availability(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("available_at must include a timezone")
        return value.astimezone(timezone.utc)

    @field_validator("pickup_location", "description")
    @classmethod
    def normalize_optional_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def availability_precedes_deadline(self):
        if self.available_at and self.available_at >= self.pickup_deadline:
            raise ValueError("available_at must be earlier than pickup_deadline")
        return self


class DonationCreate(DonationFields):
    donor_id: str


class DonationUpdateRequest(DonationFields):
    actor_id: str


class ClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ngo_id: str


class StatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_id: str
    status: Literal["cancelled", "picked_up"]


class AccountStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_id: str
    status: Literal["active", "suspended"]


class ClaimCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StatusCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["cancelled", "picked_up"]


class Principal(BaseModel):
    subject: str = Field(min_length=1)
    groups: frozenset[str] = frozenset()

    @property
    def role(self) -> Literal["donor", "ngo", "admin"] | None:
        role_groups = {
            "food-admins": "admin",
            "food-ngos": "ngo",
            "food-donors": "donor",
        }
        assigned_roles = {
            role for group, role in role_groups.items() if group in self.groups
        }
        return next(iter(assigned_roles)) if len(assigned_roles) == 1 else None
