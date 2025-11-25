# schemas.py
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List

# --- Базовые схемы ---

class OperatorBase(BaseModel):
    name: str
    
class SourceBase(BaseModel):
    name: str

# --- Схемы для создания ---

class OperatorCreate(OperatorBase):
    is_active: bool = True
    max_active_leads: int = Field(default=5, gt=0)

class SourceCreate(SourceBase):
    pass

class DistributionConfigCreate(BaseModel):
    operator_id: int
    weight: int = Field(default=10, gt=0)

# --- Схемы для ответов ---

class OperatorResponse(OperatorBase):
    id: int
    is_active: bool
    max_active_leads: int
    
    class Config:
        from_attributes = True
        
class SourceResponse(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True

class ContactResponse(BaseModel):
    id: int
    lead_id: int
    source_id: int
    operator_id: Optional[int] = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

class LeadResponse(BaseModel):
    id: int
    external_id: str
    contacts: List[ContactResponse] = []

    class Config:
        from_attributes = True

# --- Схема для регистрации обращения ---

class ContactRegister(BaseModel):
    external_id: str
    source_name: str 
    
class ContactRegistrationResult(BaseModel):
    contact: ContactResponse
    assigned_operator: Optional[OperatorResponse] = None