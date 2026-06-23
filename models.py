from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(String, unique=True, index=True)
    first_name = Column(String)
    last_name = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    samples = relationship("Sample", back_populates="patient")

class Sample(Base):
    __tablename__ = "samples"

    id = Column(Integer, primary_key=True, index=True)
    sample_id = Column(String, unique=True, index=True)
    sample_type = Column(String)  # e.g., Blood, Tissue, Saliva
    storage_location = Column(String)
    file_path = Column(String)
    patient_id = Column(Integer, ForeignKey("patients.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    patient = relationship("Patient", back_populates="samples")
