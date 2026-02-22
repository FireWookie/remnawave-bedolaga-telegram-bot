"""
Сервис рекуррентных платежей YooKassa.
Автоматически списывает средства за подписки с сохранённых карт.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import structlog
from aiogram import Bot

from app.config import settings
from app.database.database import AsyncSessionLocal


logger = structlog.get_logger(__name__)


class YooKassaRecurringService:
    """
    Фоновый сервис, который проверяет подписки с autopay_enabled=True
    и выполняет рекуррентные списания через сохранённые карты YooKassa.
    """

    def __init__(self):
        self._running = False
        self._bot: Bot | None = None
        self._check_interval_minutes = 60

    def set_bot(self, bot: Bot):
        self._bot = bot

    def is_enabled(self) -> bool:
        return (
            getattr(settings, 'YOOKASSA_RECURRING_ENABLED', False)
            and settings.is_yookassa_enabled()
        )

    def get_check_interval_minutes(self) -> int:
        return getattr(settings, 'YOOKASSA_RECURRING_CHECK_INTERVAL_MINUTES', 60)

    def stop_monitoring(self):
        self._running = False

    async def start_monitoring(self):
        """Запускает фоновый цикл проверки подписок."""
        if not self.is_enabled():
            logger.info('Рекуррентные платежи YooKassa отключены настройками')
            return

        self._running = True
        self._check_interval_minutes = self.get_check_interval_minutes()

        logger.info(
            'Запуск сервиса рекуррентных платежей YooKassa',
            interval_minutes=self._check_interval_minutes,
        )

        while self._running:
            try:
                await self.process_recurring_charges()
            except Exception as e:
                logger.error('Ошибка в цикле рекуррентных платежей', error=e, exc_info=True)

            await asyncio.sleep(self._check_interval_minutes * 60)

    async def process_recurring_charges(self) -> dict:
        """
        Находит подписки, которые:
        - autopay_enabled = True
        - expires_at <= now + autopay_days_before
        - status = 'active'
        - Пользователь имеет активный YooKassaSavedPaymentMethod

        Для каждой выполняет рекуррентное списание.
        """
        stats = {
            'checked': 0,
            'charged': 0,
            'no_method': 0,
            'failed': 0,
            'skipped': 0,
        }

        try:
            async with AsyncSessionLocal() as db:
                subscriptions = await self._get_subscriptions_for_recurring(db)
                stats['checked'] = len(subscriptions)

                if not subscriptions:
                    logger.debug('Нет подписок для рекуррентного списания')
                    return stats

                logger.info(
                    'Найдено подписок для рекуррентного списания',
                    count=len(subscriptions),
                )

                for subscription in subscriptions:
                    try:
                        result = await self._process_single_recurring(db, subscription)
                        if result == 'charged':
                            stats['charged'] += 1
                        elif result == 'no_method':
                            stats['no_method'] += 1
                        elif result == 'failed':
                            stats['failed'] += 1
                        else:
                            stats['skipped'] += 1
                    except Exception as e:
                        stats['failed'] += 1
                        logger.error(
                            'Ошибка рекуррентного списания для подписки',
                            subscription_id=subscription.id,
                            error=e,
                            exc_info=True,
                        )

        except Exception as e:
            logger.error('Ошибка получения подписок для рекуррентного списания', error=e, exc_info=True)

        if stats['charged'] > 0 or stats['failed'] > 0:
            logger.info('Результаты рекуррентных списаний', **stats)

        return stats

    async def _get_subscriptions_for_recurring(self, db):
        """Находит подписки, готовые к рекуррентному списанию."""
        from sqlalchemy import and_, select
        from sqlalchemy.orm import selectinload

        from app.database.models import Subscription, SubscriptionStatus

        now = datetime.now(UTC)

        result = await db.execute(
            select(Subscription)
            .options(selectinload(Subscription.user))
            .where(
                and_(
                    Subscription.status == SubscriptionStatus.ACTIVE.value,
                    Subscription.autopay_enabled == True,
                    Subscription.expires_at != None,
                )
            )
        )
        all_subscriptions = result.scalars().all()

        # Filter by autopay_days_before
        eligible = []
        for sub in all_subscriptions:
            if not sub.expires_at:
                continue
            days_before = sub.autopay_days_before or 3
            threshold = sub.expires_at - timedelta(days=days_before)
            if now >= threshold:
                eligible.append(sub)

        return eligible

    async def _process_single_recurring(self, db, subscription) -> str:
        """Обрабатывает одну подписку для рекуррентного списания."""
        from app.database.crud.yookassa_saved_payment_method import get_active_saved_methods

        user = subscription.user
        if not user:
            logger.warning('Пользователь не найден для подписки', subscription_id=subscription.id)
            return 'skipped'

        # Check if user has active saved payment methods
        saved_methods = await get_active_saved_methods(db, user.id)
        if not saved_methods:
            logger.info(
                'Нет сохранённых методов для рекуррентного списания',
                user_id=user.id,
                subscription_id=subscription.id,
            )
            # Notify user they need to add a card
            await self._notify_no_payment_method(user)
            return 'no_method'

        # Use the most recent saved method
        saved_method = saved_methods[0]

        # Calculate renewal cost
        amount_kopeks = await self._calculate_renewal_cost(db, subscription)
        if not amount_kopeks or amount_kopeks <= 0:
            logger.warning(
                'Не удалось рассчитать стоимость продления',
                subscription_id=subscription.id,
            )
            return 'skipped'

        # Create recurring charge
        from app.services.payment_service import PaymentService

        payment_service = PaymentService(self._bot)

        description = settings.get_subscription_payment_description(amount_kopeks)
        metadata = {
            'type': 'recurring_renewal',
            'subscription_id': str(subscription.id),
            'user_id': str(user.id),
            'user_telegram_id': str(user.telegram_id) if user.telegram_id else '',
        }

        result = await payment_service.create_recurring_charge(
            db=db,
            user_id=user.id,
            saved_method_id=saved_method.id,
            amount_kopeks=amount_kopeks,
            description=description,
            metadata=metadata,
        )

        if result and result.get('status') == 'succeeded':
            logger.info(
                'Рекуррентное списание успешно',
                user_id=user.id,
                subscription_id=subscription.id,
                amount_kopeks=amount_kopeks,
            )
            await self._notify_recurring_success(user, amount_kopeks)
            return 'charged'

        logger.warning(
            'Рекуррентное списание не удалось',
            user_id=user.id,
            subscription_id=subscription.id,
            result=result,
        )
        await self._notify_recurring_failure(user, amount_kopeks)
        return 'failed'

    async def _calculate_renewal_cost(self, db, subscription) -> int | None:
        """Рассчитывает стоимость продления подписки в копейках."""
        try:
            period_days = 30  # Default
            if hasattr(subscription, 'tariff_id') and subscription.tariff_id:
                from app.database.crud.tariff import get_tariff_by_id

                tariff = await get_tariff_by_id(db, subscription.tariff_id)
                if tariff:
                    return tariff.price_kopeks
            # Fallback: use period prices from settings
            price = settings.get_period_price_kopeks(period_days)
            return price if price and price > 0 else None
        except Exception as e:
            logger.error('Ошибка расчёта стоимости продления', error=e, exc_info=True)
            return None

    async def _notify_recurring_success(self, user, amount_kopeks: int):
        """Уведомляет пользователя об успешном рекуррентном списании."""
        if not self._bot or not user.telegram_id:
            return
        try:
            await self._bot.send_message(
                chat_id=user.telegram_id,
                text=(
                    f'✅ <b>Автоматическое продление подписки</b>\n\n'
                    f'💳 Списано: {settings.format_price(amount_kopeks)}\n'
                    f'Подписка продлена автоматически с сохранённой карты.'
                ),
                parse_mode='HTML',
            )
        except Exception as e:
            logger.warning('Ошибка уведомления о рекуррентном платеже', error=e)

    async def _notify_recurring_failure(self, user, amount_kopeks: int):
        """Уведомляет пользователя о неудачном рекуррентном списании."""
        if not self._bot or not user.telegram_id:
            return
        try:
            await self._bot.send_message(
                chat_id=user.telegram_id,
                text=(
                    f'⚠️ <b>Не удалось продлить подписку автоматически</b>\n\n'
                    f'💳 Сумма: {settings.format_price(amount_kopeks)}\n'
                    f'Пожалуйста, пополните баланс или обновите данные карты.'
                ),
                parse_mode='HTML',
            )
        except Exception as e:
            logger.warning('Ошибка уведомления о неудачном рекуррентном платеже', error=e)

    async def _notify_no_payment_method(self, user):
        """Уведомляет пользователя об отсутствии сохранённой карты."""
        if not self._bot or not user.telegram_id:
            return
        try:
            await self._bot.send_message(
                chat_id=user.telegram_id,
                text=(
                    '⚠️ <b>Автопродление подписки невозможно</b>\n\n'
                    'У вас нет сохранённой карты для автоматического списания.\n'
                    'Пожалуйста, оплатите подписку вручную или пополните баланс.'
                ),
                parse_mode='HTML',
            )
        except Exception as e:
            logger.warning('Ошибка уведомления об отсутствии карты', error=e)


yookassa_recurring_service = YooKassaRecurringService()
