"""Saved payment methods routes for cabinet."""

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.crud.yookassa_saved_payment_method import (
    deactivate_saved_method,
    get_active_saved_methods,
)
from app.database.models import User

from ..dependencies import get_cabinet_db, get_current_cabinet_user
from ..schemas.saved_payment_methods import (
    DeleteSavedMethodResponse,
    SavedPaymentMethodResponse,
    SavedPaymentMethodsListResponse,
)


logger = structlog.get_logger(__name__)

router = APIRouter(prefix='/saved-payment-methods', tags=['Cabinet Saved Payment Methods'])


@router.get('', response_model=SavedPaymentMethodsListResponse)
async def list_saved_payment_methods(
    user: User = Depends(get_current_cabinet_user),
    db: AsyncSession = Depends(get_cabinet_db),
):
    """Get list of active saved payment methods for current user."""
    methods = await get_active_saved_methods(db, user.id)

    items = [
        SavedPaymentMethodResponse(
            id=m.id,
            payment_method_type=m.payment_method_type,
            card_last_four=m.card_last_four,
            card_type=m.card_type,
            card_expiry_month=m.card_expiry_month,
            card_expiry_year=m.card_expiry_year,
            title=m.title,
            is_active=m.is_active,
            created_at=m.created_at,
        )
        for m in methods
    ]

    return SavedPaymentMethodsListResponse(items=items, total=len(items))


@router.delete('/{method_id}', response_model=DeleteSavedMethodResponse)
async def delete_saved_payment_method(
    method_id: int,
    user: User = Depends(get_current_cabinet_user),
    db: AsyncSession = Depends(get_cabinet_db),
):
    """Deactivate (unlink) a saved payment method by ID."""
    # Fetch active methods and check ownership
    methods = await get_active_saved_methods(db, user.id)
    method = next((m for m in methods if m.id == method_id), None)

    if not method:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Saved payment method not found',
        )

    await deactivate_saved_method(db, method_id)

    logger.info(
        'User deactivated saved payment method',
        user_id=user.id,
        method_id=method_id,
    )

    return DeleteSavedMethodResponse(
        success=True,
        message='Payment method successfully unlinked',
    )
