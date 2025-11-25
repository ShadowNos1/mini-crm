# services.py
import random
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from typing import List, Dict, Optional, Tuple

from models import Lead, Source, Operator, DistributionConfig, Contact 
import schemas

class ServiceException(Exception):
    """Общая ошибка сервиса."""
    pass

class SourceNotFound(ServiceException):
    """Источник не найден."""
    pass


class DistributionService:

    @staticmethod
    async def get_or_create_lead(db: AsyncSession, external_id: str) -> Lead:
        """Находит клиента по ID или создает нового."""
        stmt = select(Lead).where(Lead.external_id == external_id)
        result = await db.execute(stmt)
        lead = result.scalar_one_or_none()

        if lead is None:
            lead = Lead(external_id=external_id)
            db.add(lead)
            await db.flush() 
        
        return lead

    @staticmethod
    async def get_source_by_name(db: AsyncSession, name: str) -> Source:
        """Находит источник по имени."""
        stmt = select(Source).where(Source.name == name)
        result = await db.execute(stmt)
        source = result.scalar_one_or_none()
        
        if source is None:
            raise SourceNotFound(f"Источник '{name}' не настроен.")
            
        return source

    @staticmethod
    async def get_available_operators(db: AsyncSession, source_id: int) -> List[Dict]:
        """
        Ищет активных операторов для источника, не превысивших свой лимит.
        """
        # 1. Конфигурация и активные операторы
        stmt_config = select(DistributionConfig, Operator).join(Operator).where(
            DistributionConfig.source_id == source_id,
            Operator.is_active == True
        )
        result_config = await db.execute(stmt_config)
        configs = result_config.all()

        if not configs:
            return []

        operator_ids = [c.operator_id for config, c in configs]
        
        # 2. Расчет текущей нагрузки ('ACTIVE' контакты)
        
        if not operator_ids:
             return []
             
        stmt_load = select(
            Contact.operator_id, 
            func.count(Contact.id).label("current_load")
        ).where(
            Contact.operator_id.in_(operator_ids),
            Contact.status == 'ACTIVE' 
        ).group_by(Contact.operator_id)

        result_load = await db.execute(stmt_load)
        load_map = {row.operator_id: row.current_load for row in result_load}

        # 3. Фильтрация по лимиту
        available_operators = []
        for config, operator in configs:
            current_load = load_map.get(operator.id, 0)
            if current_load < operator.max_active_leads:
                available_operators.append({
                    "operator_id": operator.id,
                    "weight": config.weight,
                })
        
        return available_operators

    @staticmethod
    async def weighted_random_choice(available: List[Dict]) -> Optional[int]:
        """Случайный выбор по весам (доле трафика)."""
        if not available:
            return None

        weights = [op['weight'] for op in available]
        operators = [op['operator_id'] for op in available]

        chosen_id = random.choices(operators, weights=weights, k=1)[0]
        return chosen_id

    @staticmethod
    async def process_contact(
        db: AsyncSession, 
        external_id: str, 
        source_name: str
    ) -> Tuple[Contact, Optional[Operator]]:
        """
        Обработка нового обращения: ищет лида, выбирает оператора и сохраняет контакт.
        """
        lead = await DistributionService.get_or_create_lead(db, external_id)
        source = await DistributionService.get_source_by_name(db, source_name)
        
        available_operators = await DistributionService.get_available_operators(db, source.id)
        chosen_operator_id = await DistributionService.weighted_random_choice(available_operators)
        
        assigned_operator: Optional[Operator] = None
        if chosen_operator_id:
            stmt_op = select(Operator).where(Operator.id == chosen_operator_id)
            result_op = await db.execute(stmt_op)
            
            assigned_operator = result_op.scalar_one_or_none() 
            
            if assigned_operator is None:
                 chosen_operator_id = None 

        new_contact = Contact(
            lead_id=lead.id,
            source_id=source.id,
            operator_id=chosen_operator_id, 
            status='ACTIVE' 
        )
        db.add(new_contact)
        
        await db.commit()
        await db.refresh(new_contact)
        
        # Гарантируем, что объект оператора полностью загружен
        if assigned_operator:
             await db.refresh(assigned_operator)
             # >>> КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Отвязываем объект от сессии
             db.expunge(assigned_operator)
        
        return new_contact, assigned_operator