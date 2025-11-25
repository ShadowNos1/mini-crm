# main.py
from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from typing import Annotated, List

from database import init_db, get_db_session
import models
from schemas import (
    OperatorCreate, OperatorResponse,
    SourceCreate, SourceResponse,
    DistributionConfigCreate,
    ContactRegister, ContactResponse, ContactRegistrationResult,
    LeadResponse
)
from services import DistributionService, SourceNotFound

app = FastAPI(
    title="Мини-CRM Распределения Лидов",
    version="1.0.0"
)

DBSession = Annotated[AsyncSession, Depends(get_db_session)]

@app.on_event("startup")
async def startup_event():
    """Создание таблиц при запуске."""
    await init_db()

# --- 1. Управление операторами ---

@app.post("/operators/", response_model=OperatorResponse, status_code=status.HTTP_201_CREATED)
async def create_operator(data: OperatorCreate, db: DBSession):
    """Добавить нового оператора."""
    new_operator = models.Operator(**data.model_dump())
    db.add(new_operator)
    try:
        await db.commit()
        await db.refresh(new_operator)
        return new_operator
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"Ошибка создания: {e}")

@app.get("/operators/", response_model=List[OperatorResponse])
async def read_operators(db: DBSession):
    """Показать всех операторов."""
    stmt = select(models.Operator)
    result = await db.execute(stmt)
    return result.scalars().all()

@app.put("/operators/{operator_id}", response_model=OperatorResponse)
async def update_operator(operator_id: int, data: OperatorCreate, db: DBSession):
    """Изменить лимит или активность оператора."""
    stmt = select(models.Operator).where(models.Operator.id == operator_id)
    result = await db.execute(stmt)
    operator = result.scalar_one_or_none()
    
    if operator is None:
        raise HTTPException(status_code=404, detail="Оператор не найден")

    operator.name = data.name
    operator.is_active = data.is_active
    operator.max_active_leads = data.max_active_leads

    await db.commit()
    await db.refresh(operator)
    return operator

# --- 2. Настройка распределения по источникам ---

@app.post("/sources/", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(data: SourceCreate, db: DBSession):
    """Добавить новый источник (бот)."""
    new_source = models.Source(**data.model_dump())
    db.add(new_source)
    try:
        await db.commit()
        await db.refresh(new_source)
        return new_source
    except Exception as e:
        await db.rollback()
        if "UNIQUE constraint failed" in str(e):
            raise HTTPException(
                status_code=400, 
                detail=f"Источник с именем '{data.name}' уже существует."
            )
        raise HTTPException(status_code=500, detail=f"Ошибка создания источника: {e}")


@app.get("/sources/", response_model=List[SourceResponse])
async def read_sources(db: DBSession):
    """Показать список всех источников."""
    stmt = select(models.Source)
    result = await db.execute(stmt)
    return result.scalars().all()

@app.post("/sources/{source_id}/config", status_code=status.HTTP_201_CREATED)
async def configure_source_distribution(source_id: int, configs: List[DistributionConfigCreate], db: DBSession):
    """Настроить операторов и их веса для источника."""
    
    # Проверка источника
    stmt_source = select(models.Source).where(models.Source.id == source_id)
    if (await db.execute(stmt_source)).scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Источник не найден")
    
    # Проверка на дублирование ID операторов во входном списке
    operator_ids = [cfg.operator_id for cfg in configs]
    if len(operator_ids) != len(set(operator_ids)):
        raise HTTPException(status_code=400, detail="Входной список конфигураций содержит дублирующиеся ID операторов.")

    # Удаляем старые конфиги для обновления
    await db.execute(models.DistributionConfig.__table__.delete().where(models.DistributionConfig.source_id == source_id))
    
    # Добавляем новые конфиги
    new_configs = []
    for cfg in configs:
        # Проверка оператора
        stmt_op = select(models.Operator).where(models.Operator.id == cfg.operator_id)
        if (await db.execute(stmt_op)).scalar_one_or_none() is None:
            raise HTTPException(status_code=400, detail=f"Оператор ID {cfg.operator_id} не найден.")
            
        new_configs.append(
            models.DistributionConfig(
                source_id=source_id,
                operator_id=cfg.operator_id,
                weight=cfg.weight
            )
        )
    
    db.add_all(new_configs)
    await db.commit()
    return {"message": f"Конфигурация для источника ID {source_id} обновлена."}


# --- 3. Регистрация обращения (Ключевая логика) ---

@app.post("/contacts/register", response_model=ContactRegistrationResult)
async def register_contact(data: ContactRegister, db: DBSession):
    """
    Регистрация нового обращения. 
    Находит/создает лида и распределяет по оператору согласно весам и лимитам.
    """
    try:
        contact, operator = await DistributionService.process_contact(
            db=db,
            external_id=data.external_id,
            source_name=data.source_name
        )
        
        validated_operator = None
        
        if isinstance(operator, models.Operator):
            # >>> ФИНАЛЬНОЕ ИСПРАВЛЕНИЕ: Ручное создание словаря
            # Это полностью исключает конфликт Pydantic/SQLAlchemy.
            operator_data = {
                "id": operator.id,
                "name": operator.name,
                "is_active": operator.is_active,
                "max_active_leads": operator.max_active_leads,
            }
            validated_operator = OperatorResponse(**operator_data)
        
        return ContactRegistrationResult(
            contact=ContactResponse.model_validate(contact),
            assigned_operator=validated_operator
        )
    except SourceNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        print(f"CRITICAL ERROR IN DISTRIBUTION: {e}")
        # Возвращаем общую ошибку 500
        raise HTTPException(status_code=500, detail=f"Ошибка распределения: {e}")

# --- 4. Просмотр состояния ---

@app.get("/leads/{lead_id}", response_model=LeadResponse)
async def read_lead_details(lead_id: int, db: DBSession):
    """Показать лида и все его обращения."""
    stmt = (
        select(models.Lead)
        .where(models.Lead.id == lead_id)
        .options(models.relationship("contacts")) 
    )
    result = await db.execute(stmt)
    lead = result.scalar_one_or_none()

    if lead is None:
        raise HTTPException(status_code=404, detail="Лид не найден")
    
    return lead

@app.get("/distribution_status/")
async def get_distribution_status(db: DBSession):
    """
    Показать сводку распределения: сколько обращений у кого и откуда.
    """
    stmt = select(
        models.Operator.name.label("operator_name"),
        models.Source.name.label("source_name"),
        func.count(models.Contact.id).label("total_contacts"),
        func.sum(func.case((models.Contact.status == 'ACTIVE', 1), else_=0)).label("active_contacts")
    ).select_from(models.Contact).join(models.Operator, isouter=True).join(models.Source).group_by(
        models.Operator.name, models.Source.name
    ).order_by(models.Source.name, models.Operator.name)

    result = await db.execute(stmt)
    distribution_data = [dict(row._mapping) for row in result.all()]
    
    stmt_op = select(models.Operator.name, models.Operator.max_active_leads)
    op_limits = {name: limit for name, limit in (await db.execute(stmt_op)).all()}

    return {
        "operator_limits": op_limits,
        "distribution_summary": distribution_data,
        "note": "Если operator_name = null, значит, оператор не был назначен (нет доступных)."
    }