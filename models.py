# models.py
from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.orm import declarative_base 
from typing import List, Optional
from datetime import datetime

Base = declarative_base()
    
# --- 1. Операторы ---

class Operator(Base):
    __tablename__ = 'operators'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    is_active: Mapped[bool]
    max_active_leads: Mapped[int] 

    contacts: Mapped[List["Contact"]] = relationship(back_populates="operator")
    configs: Mapped[List["DistributionConfig"]] = relationship(back_populates="operator")
    
# --- 2. Источники ---

class Source(Base):
    __tablename__ = 'sources'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True) 

    configs: Mapped[List["DistributionConfig"]] = relationship(back_populates="source")

# --- 3. Конфигурация распределения (Веса) ---

class DistributionConfig(Base):
    __tablename__ = 'distribution_configs'
    source_id: Mapped[int] = mapped_column(ForeignKey('sources.id'), primary_key=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey('operators.id'), primary_key=True)
    weight: Mapped[int] 

    source: Mapped["Source"] = relationship(back_populates="configs")
    operator: Mapped["Operator"] = relationship(back_populates="configs")
    
# --- 4. Лиды (Клиенты) ---

class Lead(Base):
    __tablename__ = 'leads'
    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(unique=True) 

    contacts: Mapped[List["Contact"]] = relationship(back_populates="lead")

# --- 5. Обращения (Контакты) ---

class Contact(Base):
    __tablename__ = 'contacts'
    id: Mapped[int] = mapped_column(primary_key=True)
    
    lead_id: Mapped[int] = mapped_column(ForeignKey('leads.id'))
    source_id: Mapped[int] = mapped_column(ForeignKey('sources.id'))
    
    operator_id: Mapped[Optional[int]] = mapped_column(ForeignKey('operators.id'), nullable=True) 
    
    status: Mapped[str] = mapped_column(default="ACTIVE") 
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    lead: Mapped["Lead"] = relationship(back_populates="contacts")
    source: Mapped["Source"] = relationship()
    operator: Mapped[Optional["Operator"]] = relationship(back_populates="contacts")