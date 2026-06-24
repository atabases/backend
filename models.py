from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    study_id = Column(String, index=True)
    patient_id = Column(String, index=True)
    diagnosis = Column(String)
    stage = Column(String)
    diagnosis_age = Column(Float)
    sex = Column(String)
    ethnicity = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    samples = relationship("Sample", back_populates="patient", cascade="all, delete-orphan")

class Sample(Base):
    __tablename__ = "samples"

    id = Column(Integer, primary_key=True, index=True)
    study_id = Column(String, index=True)
    sample_id = Column(String, index=True)
    immunohistochemistry = Column(String)
    oncotree_code = Column(String)
    cancer_type = Column(String)
    cancer_type_detailed = Column(String)
    somatic_status = Column(String)
    tmb_nonsynonymous = Column(Float)
    patient_id = Column(Integer, ForeignKey("patients.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    patient = relationship("Patient", back_populates="samples")
    mutations = relationship("Mutation", back_populates="sample", cascade="all, delete-orphan")

class Mutation(Base):
    __tablename__ = "mutations"

    id = Column(Integer, primary_key=True, index=True)
    hugo_symbol = Column(String, index=True)
    protein_change = Column(String)
    annotation = Column(String)
    mutation_type = Column(String)
    sample_id = Column(Integer, ForeignKey("samples.id"))
    
    sample = relationship("Sample", back_populates="mutations")
