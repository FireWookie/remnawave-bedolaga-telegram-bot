"""Saved payment methods schemas for cabinet."""

from datetime import datetime

from pydantic import BaseModel


class SavedPaymentMethodResponse(BaseModel):
    """Saved payment method data."""

    id: int
    payment_method_type: str | None = None
    card_last_four: str | None = None
    card_type: str | None = None
    card_expiry_month: str | None = None
    card_expiry_year: str | None = None
    title: str | None = None
    is_active: bool
    created_at: datetime | None = None

    class Config:
        from_attributes = True


class SavedPaymentMethodsListResponse(BaseModel):
    """List of saved payment methods."""

    items: list[SavedPaymentMethodResponse]
    total: int


class DeleteSavedMethodResponse(BaseModel):
    """Response for delete saved method."""

    success: bool
    message: str
