import os
import shutil
from typing import List
from fastapi import FastAPI, Depends, HTTPException, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

import models, schemas, database
from database import engine, get_db

# Create database tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Biobank & Genomics API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Welcome to the Biobank & Genomics API"}

@app.get("/api/health")
async def health():
    return {"status": "healthy"}

# Patient Endpoints
@app.post("/api/patients", response_model=schemas.Patient)
def create_patient(patient: schemas.PatientCreate, db: Session = Depends(get_db)):
    try:
        db_patient = models.Patient(**patient.model_dump())
        db.add(db_patient)
        db.commit()
        db.refresh(db_patient)
        return db_patient
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/patients", response_model=List[schemas.Patient])
def read_patients(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    patients = db.query(models.Patient).offset(skip).limit(limit).all()
    return patients

# Sample Endpoints
@app.post("/api/samples", response_model=schemas.Sample)
def create_sample(sample: schemas.SampleCreate, db: Session = Depends(get_db)):
    db_sample = models.Sample(**sample.model_dump())
    db.add(db_sample)
    db.commit()
    db.refresh(db_sample)
    return db_sample

@app.get("/api/samples", response_model=List[schemas.Sample])
def read_samples(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    samples = db.query(models.Sample).offset(skip).limit(limit).all()
    return samples

# Genomic File Upload
@app.post("/api/upload", response_model=schemas.Sample)
async def upload_file(
    patient_id: int = Form(...),
    sample_id: str = Form(...),
    sample_type: str = Form(...),
    storage_location: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    # 1. Validate File Extension
    allowed_extensions = {".vcf", ".fasta", ".fastq"}
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid file type. Allowed: {allowed_extensions}"
        )

    # 2. Ensure Patient Exists
    db_patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not db_patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # 3. Create Directory Path
    upload_dir = f"/data/{db_patient.patient_id}"
    os.makedirs(upload_dir, exist_ok=True)
    
    file_path = os.path.join(upload_dir, file.filename)

    # 4. Save File in Chunks (for large files)
    try:
        with open(file_path, "wb") as buffer:
            while True:
                chunk = await file.read(1024 * 1024)  # 1MB chunks
                if not chunk:
                    break
                buffer.write(chunk)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File save failed: {str(e)}")

    # 5. Update Database
    try:
        db_sample = models.Sample(
            sample_id=sample_id,
            sample_type=sample_type,
            storage_location=storage_location,
            file_path=file_path,
            patient_id=patient_id
        )
        db.add(db_sample)
        db.commit()
        db.refresh(db_sample)
        return db_sample
    except Exception as e:
        db.rollback()
        # Cleanup file if DB update fails
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=str(e))
