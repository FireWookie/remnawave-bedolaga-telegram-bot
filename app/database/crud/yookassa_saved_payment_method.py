from datetime import UTC, datetime

import structlog
from sqlalchemy import and_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import YooKassaSavedPaymentMethod


logger = structlog.get_logger(__name__)


async def create_saved_payment_method(
    db: AsyncSession,
    user_id: int,
    payment_method_id: str,
    payment_method_type: str | None = None,
    card_first_six: str | None = None,
    card_last_four: str | None = None,
    card_type: str | None = None,
    card_expiry_month: str | None = None,
    card_expiry_year: str | None = None,
    title: str | None = None,
    source_payment_id: int | None = None,
) -> YooKassaSavedPaymentMethod | None:
    """Создаёт запись сохранённого платёжного метода."""
    method = YooKassaSavedPaymentMethod(
        user_id=user_id,
        payment_method_id=payment_method_id,
        payment_method_type=payment_method_type,
        card_first_six=card_first_six,
        card_last_four=card_last_four,
        card_type=card_type,
        card_expiry_month=card_expiry_month,
        card_expiry_year=card_expiry_year,
        title=title,
        source_payment_id=source_payment_id,
        is_active=True,
    )

    db.add(method)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.warning(
            'Сохранённый метод уже существует',
            payment_method_id=payment_method_id,
            user_id=user_id,
        )
        return await get_saved_method_by_payment_method_id(db, payment_method_id)
    await db.refresh(method)

    logger.info(
        'Создан сохранённый платёжный метод',
        payment_method_id=payment_method_id,
        user_id=user_id,
        title=title,
    )
    return method


async def get_active_saved_methods(
    db: AsyncSession,
    user_id: int,
) -> list[YooKassaSavedPaymentMethod]:
    """Возвращает все активные сохранённые методы пользователя."""
    result = await db.execute(
        select(YooKassaSavedPaymentMethod)
        .where(
            and_(
                YooKassaSavedPaymentMethod.user_id == user_id,
                YooKassaSavedPaymentMethod.is_active == True,
            )
        )
        .order_by(YooKassaSavedPaymentMethod.created_at.desc())
    )
    return list(result.scalars().all())


async def get_saved_method_by_payment_method_id(
    db: AsyncSession,
    payment_method_id: str,
) -> YooKassaSavedPaymentMethod | None:
    """Ищет сохранённый метод по ID от YooKassa."""
    result = await db.execute(
        select(YooKassaSavedPaymentMethod).where(
            YooKassaSavedPaymentMethod.payment_method_id == payment_method_id
        )
    )
    return result.scalar_one_or_none()


async def deactivate_saved_method(
    db: AsyncSession,
    method_id: int,
) -> None:
    """Деактивирует сохранённый метод по ID."""
    await db.execute(
        update(YooKassaSavedPaymentMethod)
        .where(YooKassaSavedPaymentMethod.id == method_id)
        .values(is_active=False, updated_at=datetime.now(UTC))
    )
    await db.commit()
    logger.info('Деактивирован сохранённый метод', method_id=method_id)


async def deactivate_all_user_methods(
    db: AsyncSession,
    user_id: int,
) -> None:
    """Деактивирует все сохранённые методы пользователя."""
    await db.execute(
        update(YooKassaSavedPaymentMethod)
        .where(
            and_(
                YooKassaSavedPaymentMethod.user_id == user_id,
                YooKassaSavedPaymentMethod.is_active == True,
            )
        )
        .values(is_active=False, updated_at=datetime.now(UTC))
    )
    await db.commit()
    logger.info('Деактивированы все методы пользователя', user_id=user_id)
