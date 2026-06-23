from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional

class SampleBase(BaseModel):
    sample_id: str
    sample_type: str
    storage_location: str
    file_path: Optional[str] = None

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
    first_name: str
    last_name: str

class PatientCreate(PatientBase):
    pass

class Patient(PatientBase):
    id: int
    created_at: datetime
    samples: List[Sample] = []

    class Config:
        from_attributes = True
