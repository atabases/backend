from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional

class SampleBase(BaseModel):
    sample_id: str
    immunohistochemistry: Optional[str] = None
    oncotree_code: Optional[str] = None
    cancer_type: Optional[str] = None
    cancer_type_detailed: Optional[str] = None
    somatic_status: Optional[str] = None
    tmb_nonsynonymous: Optional[float] = None

class SampleCreate(SampleBase):
    patient_id: int

class Sample(SampleBase):
    id: int
    patient_id: int
    created_at: datetime

    class Config:
        from_attributes = True

class PatientBase(BaseModel):
    patient_id: str
    diagnosis: Optional[str] = None
    stage: Optional[str] = None
    diagnosis_age: Optional[float] = None
    sex: Optional[str] = None
    ethnicity: Optional[str] = None

class PatientCreate(PatientBase):
    pass

class Patient(PatientBase):
    id: int
    created_at: datetime
    samples: List[Sample] = []

    class Config:
        from_attributes = True
