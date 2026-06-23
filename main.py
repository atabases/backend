import os
from typing import List
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from fastapi import UploadFile, File, Form
from sqlalchemy import text
import models, schemas
from database import engine, get_db

# Ensure tables exist
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Biobank Clinical Dashboard API")

# Configure CORS for Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Biobank Dashboard API Active"}


@app.get("/api/dashboard/data")
def get_dashboard_data(study_id: str = None, db: Session = Depends(get_db)):
    """
    Returns aggregated data for all charts and tables in the dashboard grid.
    """
    # 1. Base queries for patients and samples
    patient_query = db.query(models.Patient)
    sample_query = db.query(models.Sample)
    if study_id:
        patient_query = patient_query.filter(models.Patient.study_id == study_id)
        sample_query = sample_query.filter(models.Sample.study_id == study_id)

    total_patients = patient_query.count()
    total_samples = sample_query.count()

    # Helper for generic group by distribution
    def get_distribution(model, column):
        query = db.query(column, func.count(model.id))
        if study_id:
            query = query.filter(model.study_id == study_id)
        result = query.group_by(column).all()
        # Filter out None/Null strings and label them "NA" or "Unknown"
        dist = []
        for row in result:
            val = row[0]
            count = row[1]
            if val is None or str(val).strip() == "":
                name = "Unknown"
            else:
                name = str(val)
            dist.append({"name": name, "value": count})
        return dist

    # --- PIE CHARTS ---
    cancer_type = get_distribution(models.Sample, models.Sample.cancer_type)
    cancer_type_detailed = get_distribution(models.Sample, models.Sample.cancer_type_detailed)
    diagnosis = get_distribution(models.Patient, models.Patient.diagnosis)
    ethnicity = get_distribution(models.Patient, models.Patient.ethnicity)
    ihc = get_distribution(models.Sample, models.Sample.immunohistochemistry)
    oncotree = get_distribution(models.Sample, models.Sample.oncotree_code)
    sex = get_distribution(models.Patient, models.Patient.sex)
    somatic_status = get_distribution(models.Sample, models.Sample.somatic_status)
    stage = get_distribution(models.Patient, models.Patient.stage)

    # Number of samples per patient
    samples_per_patient_query = db.query(models.Sample.patient_id, func.count(models.Sample.id))
    if study_id:
        samples_per_patient_query = samples_per_patient_query.filter(models.Sample.study_id == study_id)
    samples_per_patient = samples_per_patient_query.group_by(models.Sample.patient_id).all()
    
    samples_per_patient_dist = {}
    for row in samples_per_patient:
        cnt = str(row[1])
        samples_per_patient_dist[cnt] = samples_per_patient_dist.get(cnt, 0) + 1
    samples_per_patient_chart = [{"name": k, "value": v} for k, v in samples_per_patient_dist.items()]

    # --- BAR CHARTS (Raw data arrays for frontend binning) ---
    age_query = db.query(models.Patient.diagnosis_age).filter(models.Patient.diagnosis_age != None)
    tmb_query = db.query(models.Sample.tmb_nonsynonymous).filter(models.Sample.tmb_nonsynonymous != None)
    if study_id:
        age_query = age_query.filter(models.Patient.study_id == study_id)
        tmb_query = tmb_query.filter(models.Sample.study_id == study_id)
    ages = [a[0] for a in age_query.all()]
    tmbs = [t[0] for t in tmb_query.all()]
    
    muts_per_sample_query = db.query(models.Mutation.sample_id, func.count(models.Mutation.id)).join(models.Sample)
    if study_id:
        muts_per_sample_query = muts_per_sample_query.filter(models.Sample.study_id == study_id)
    muts_per_sample = muts_per_sample_query.group_by(models.Mutation.sample_id).all()
    mutation_counts = [m[1] for m in muts_per_sample]
    
    # Profiled samples count (samples with mutation data)
    profiled_samples = len(muts_per_sample)

    # --- TABLES ---
    # Top 50 Mutated Genes
    mutated_genes_query = db.query(models.Mutation.hugo_symbol, func.count(models.Mutation.id)).join(models.Sample)
    if study_id:
        mutated_genes_query = mutated_genes_query.filter(models.Sample.study_id == study_id)
    mutated_genes = mutated_genes_query.group_by(models.Mutation.hugo_symbol).order_by(func.count(models.Mutation.id).desc()).limit(50).all()
    
    mutated_genes_table = []
    for m in mutated_genes:
        # Number of unique samples that have this mutation
        unique_samples_query = db.query(func.count(func.distinct(models.Mutation.sample_id))).join(models.Sample)
        unique_samples_query = unique_samples_query.filter(models.Mutation.hugo_symbol == m[0])
        if study_id:
            unique_samples_query = unique_samples_query.filter(models.Sample.study_id == study_id)
        unique_samples = unique_samples_query.scalar()
        freq = round((unique_samples / profiled_samples) * 100, 1) if profiled_samples > 0 else 0
        mutated_genes_table.append({
            "gene": m[0], 
            "count": m[1],
            "freq": freq
        })

    # Prepare cancer studies list
    if study_id:
        cancer_studies = [{"name": study_id, "value": total_samples}]
    else:
        study_dist = db.query(models.Sample.study_id, func.count(models.Sample.id)).group_by(models.Sample.study_id).all()
        cancer_studies = [{"name": s[0] if s[0] else "Unknown", "value": s[1]} for s in study_dist]

    return {
        "summary": {
            "patients": total_patients,
            "samples": total_samples,
            "profiled_samples": profiled_samples
        },
        "pie": {
            "cancer_studies": cancer_studies,
            "cancer_type": cancer_type,
            "cancer_type_detailed": cancer_type_detailed,
            "diagnosis": diagnosis,
            "ethnicity": ethnicity,
            "immunohistochemistry": ihc,
            "number_of_samples_per_patient": samples_per_patient_chart,
            "oncotree_code": oncotree,
            "sex": sex,
            "somatic_status": somatic_status,
            "stage": stage
        },
        "bar": {
            "diagnosis_age": ages,
            "tmb_nonsynonymous": tmbs,
            "mutation_count": mutation_counts
        },
        "tables": {
            "mutated_genes": mutated_genes_table,
            "data_types": [
                {"name": "Mutations", "count": profiled_samples, "freq": round((profiled_samples/total_samples)*100, 1) if total_samples > 0 else 0}
            ],
            "case_lists": [
                {"name": "All samples", "count": total_samples, "freq": 100.0},
                {"name": "Samples with mutation data", "count": profiled_samples, "freq": round((profiled_samples/total_samples)*100, 1) if total_samples > 0 else 0}
            ]
        }
    }

@app.get("/api/clinical-data")
def get_clinical_data(study_id: str = None, db: Session = Depends(get_db)):
    """
    Returns clinical data table rows.
    """
    # Join Patient, Sample, and count Mutations
    query = (
        db.query(
            models.Patient.patient_id,
            models.Sample.sample_id,
            func.count(models.Mutation.id).label("mutation_count"),
            models.Patient.diagnosis_age,
            models.Patient.sex,
            models.Patient.ethnicity,
            models.Patient.diagnosis,
            models.Sample.immunohistochemistry,
            models.Patient.stage,
            models.Sample.tmb_nonsynonymous
        )
        .join(models.Sample, models.Patient.id == models.Sample.patient_id)
        .outerjoin(models.Mutation, models.Sample.id == models.Mutation.sample_id)
    )

    if study_id:
        query = query.filter(models.Patient.study_id == study_id)

    query = query.group_by(
        models.Patient.patient_id,
        models.Sample.sample_id,
        models.Patient.diagnosis_age,
        models.Patient.sex,
        models.Patient.ethnicity,
        models.Patient.diagnosis,
        models.Sample.immunohistochemistry,
        models.Patient.stage,
        models.Sample.tmb_nonsynonymous
    ).all()

    results = []
    for row in query:
        results.append({
            "patientId": row.patient_id,
            "sampleId": row.sample_id,
            "mutationCount": row.mutation_count,
            "diagnosisAge": row.diagnosis_age,
            "sex": row.sex,
            "ethnicityCategory": row.ethnicity,
            "diagnosis": row.diagnosis,
            "immunohistochemistry": row.immunohistochemistry,
            "stage": row.stage,
            "tmb": row.tmb_nonsynonymous
        })

    return results

@app.get("/api/patients/{patient_id}")
def get_patient_details(patient_id: str, db: Session = Depends(get_db)):
    """
    Returns patient details including mutations.
    """
    patient = db.query(models.Patient).filter(models.Patient.patient_id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Fetch mutations for all samples of this patient
    samples = db.query(models.Sample).filter(models.Sample.patient_id == patient.id).all()
    sample_ids = [s.id for s in samples]

    mutations = []
    if sample_ids:
        muts = db.query(models.Mutation).filter(models.Mutation.sample_id.in_(sample_ids)).all()
        for m in muts:
            mutations.append({
                "gene": m.hugo_symbol,
                "proteinChange": m.protein_change if m.protein_change else "N/A",
                "annotation": m.annotation if m.annotation else "None",
                "mutationType": m.mutation_type if m.mutation_type else "Missense",
                "cohort": "N/A",
                "sample_id": m.sample_id
            })

    sample_data = []
    if samples:
        for s in samples:
            sample_muts = [m for m in mutations if m["sample_id"] == s.id]
            sample_data.append({
                "sampleId": s.sample_id,
                "mutationCount": len(sample_muts),
                "cancerType": s.cancer_type,
                "cancerTypeDetailed": s.cancer_type_detailed,
                "immunohistochemistry": s.immunohistochemistry,
                "oncotreeCode": s.oncotree_code,
                "somaticStatus": s.somatic_status,
                "tmb": s.tmb_nonsynonymous
            })

    return {
        "patientId": patient.patient_id,
        "diagnosis": patient.diagnosis,
        "diagnosisAge": patient.diagnosis_age,
        "ethnicityCategory": patient.ethnicity,
        "sex": patient.sex,
        "stage": patient.stage,
        "samples": sample_data,
        "mutations": mutations
    }

@app.get("/api/studies")
def get_studies(db: Session = Depends(get_db)):
    query = text("""
    SELECT 
        p.study_id as id,
        MAX(s.cancer_type) as category,
        COUNT(DISTINCT s.id) as samples,
        COUNT(DISTINCT m.id) as mutations
    FROM patients p
    LEFT JOIN samples s ON p.id = s.patient_id
    LEFT JOIN mutations m ON s.id = m.sample_id
    GROUP BY p.study_id
    """)
    result = db.execute(query).fetchall()
    
    studies = {}
    for r in result:
        rm = r._mapping
        cat = rm['category']
        if not cat:
            sid = rm['id'].lower()
            if 'aml' in sid or 'all_' in sid or 'alal' in sid or 'laml' in sid:
                cat = 'Leukemia'
            else:
                cat = 'Custom'
        elif 'leukemia' in cat.lower():
            cat = 'Leukemia'
            
        if cat not in studies:
            studies[cat] = []
            
        studies[cat].append({
            'id': rm['id'],
            'name': rm['id'].replace('_', ' ').title(),
            'reference': 'Uploaded',
            'samples': rm['samples'],
            'all': rm['samples'],
            'mutations': rm['mutations'],
            'cna': 0, 'rnaseq': 0, 'sv': 0, 'mrna': 0, 'mirna': 0,
            'meth': 0, 'rppa': 0, 'protein': 0, 'complete': 0, 'treatment': 0
        })
    return studies

import io
from ingest import get_field, safe_float
from database import SessionLocal

@app.post("/api/upload-study")
async def upload_study(
    study_id: str = Form(...),
    files: List[UploadFile] = File(...)
):
    db = SessionLocal()
    try:
        patients_to_add = []
        samples_to_add = []
        mutations_to_add = []
        
        patient_lines = []
        sample_lines = []
        mutation_lines = []

        for file in files:
            content = await file.read()
            text_content = content.decode('utf-8').splitlines()
            if 'patient' in file.filename.lower():
                patient_lines = text_content
            elif 'sample' in file.filename.lower() and 'tumor' not in file.filename.lower():
                sample_lines = text_content
            elif 'mutation' in file.filename.lower():
                mutation_lines = text_content
                
        # Parse patients
        if patient_lines:
            header_idx = -1
            for i, line in enumerate(patient_lines):
                if not line.startswith('#') and 'PATIENT_ID' in line:
                    header_idx = i
                    break
            if header_idx != -1:
                headers = patient_lines[header_idx].strip().split('\t')
                for line in patient_lines[header_idx+1:]:
                    if not line.strip(): continue
                    cols = line.strip().split('\t')
                    row = dict(zip(headers, cols))
                    pid = get_field(row, ['PATIENT_ID'])
                    if not pid: continue
                    patients_to_add.append(models.Patient(
                        study_id=study_id,
                        patient_id=pid,
                        diagnosis=get_field(row, ['DIAGNOSIS', 'DIAGNOSIS_AT_INCLUSION', 'PRIMARY_DIAGNOSIS']),
                        stage=get_field(row, ['STAGE', 'PATHOLOGIC_STAGE']),
                        diagnosis_age=safe_float(get_field(row, ['AGE', 'DIAGNOSIS_AGE'])),
                        sex=get_field(row, ['SEX', 'GENDER']),
                        ethnicity=get_field(row, ['ETHNICITY', 'RACE', 'ETHNICITY_CATEGORY'])
                    ))
            db.bulk_save_objects(patients_to_add)
            db.commit()

        # Parse samples
        patients_map = {p.patient_id: p.id for p in db.query(models.Patient).filter(models.Patient.study_id == study_id).all()}
        if sample_lines:
            header_idx = -1
            for i, line in enumerate(sample_lines):
                if not line.startswith('#') and ('PATIENT_ID' in line or 'SAMPLE_ID' in line):
                    header_idx = i
                    break
            if header_idx != -1:
                headers = sample_lines[header_idx].strip().split('\t')
                for line in sample_lines[header_idx+1:]:
                    if not line.strip(): continue
                    cols = line.strip().split('\t')
                    row = dict(zip(headers, cols))
                    sid = get_field(row, ['SAMPLE_ID'])
                    pid = get_field(row, ['PATIENT_ID'])
                    if not sid or not pid or pid not in patients_map: continue
                    samples_to_add.append(models.Sample(
                        study_id=study_id,
                        sample_id=sid,
                        immunohistochemistry=get_field(row, ['IMMUNOHISTOCHEMISTRY', 'IHC']),
                        oncotree_code=get_field(row, ['ONCOTREE_CODE']),
                        cancer_type=get_field(row, ['CANCER_TYPE']),
                        cancer_type_detailed=get_field(row, ['CANCER_TYPE_DETAILED']),
                        somatic_status=get_field(row, ['SOMATIC_STATUS']),
                        tmb_nonsynonymous=safe_float(get_field(row, ['TMB_NONSYNONYMOUS'])),
                        patient_id=patients_map[pid]
                    ))
            db.bulk_save_objects(samples_to_add)
            db.commit()

        # Parse mutations
        samples_map = {s.sample_id: s.id for s in db.query(models.Sample).filter(models.Sample.study_id == study_id).all()}
        if mutation_lines:
            header_idx = -1
            for i, line in enumerate(mutation_lines):
                if not line.startswith('#') and 'Hugo_Symbol' in line:
                    header_idx = i
                    break
            if header_idx != -1:
                headers = [h.strip().lower() for h in mutation_lines[header_idx].strip().split('\t')]
                try:
                    hugo_idx = headers.index('hugo_symbol')
                    sample_idx = headers.index('tumor_sample_barcode')
                    for line in mutation_lines[header_idx+1:]:
                        if not line.strip(): continue
                        cols = line.strip().split('\t')
                        if len(cols) > max(hugo_idx, sample_idx):
                            hugo = cols[hugo_idx].strip()
                            sbarcode = cols[sample_idx].strip()
                            if sbarcode in samples_map:
                                mutations_to_add.append(models.Mutation(
                                    hugo_symbol=hugo,
                                    sample_id=samples_map[sbarcode],
                                    # Basic mapping for new uploads if columns exist
                                    protein_change=cols[headers.index('hgvsp_short')] if 'hgvsp_short' in headers and len(cols)>headers.index('hgvsp_short') else None,
                                    mutation_type=cols[headers.index('variant_classification')] if 'variant_classification' in headers and len(cols)>headers.index('variant_classification') else None
                                ))
                except ValueError:
                    pass
            
            if mutations_to_add:
                db.bulk_save_objects(mutations_to_add)
                db.commit()

        return {"status": "success", "message": "Study uploaded successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

from fastapi import UploadFile, File, Form
from sqlalchemy import text
from database import SessionLocal
import io
from ingest import get_field, safe_float
import models

@app.get("/api/studies")
def get_studies(db: Session = Depends(get_db)):
    query = text("""
    SELECT 
        p.study_id as id,
        MAX(s.cancer_type) as category,
        COUNT(DISTINCT s.id) as samples,
        COUNT(DISTINCT m.id) as mutations
    FROM patients p
    LEFT JOIN samples s ON p.id = s.patient_id
    LEFT JOIN mutations m ON s.id = m.sample_id
    GROUP BY p.study_id
    """)
    result = db.execute(query).fetchall()
    
    studies = {}
    for r in result:
        rm = getattr(r, '_mapping', dict(r) if isinstance(r, dict) else r)
        cat = rm['category']
        if not cat:
            sid = rm['id'].lower()
            if 'aml' in sid or 'all_' in sid or 'alal' in sid or 'laml' in sid:
                cat = 'Leukemia'
            else:
                cat = 'Custom'
        elif 'leukemia' in cat.lower():
            cat = 'Leukemia'
            
        if cat not in studies:
            studies[cat] = []
            
        studies[cat].append({
            'id': rm['id'],
            'name': rm['id'].replace('_', ' ').title(),
            'reference': 'Uploaded Data',
            'samples': rm['samples'],
            'all': rm['samples'],
            'mutations': rm['mutations'],
            'cna': 0, 'rnaseq': 0, 'sv': 0, 'mrna': 0, 'mirna': 0,
            'meth': 0, 'rppa': 0, 'protein': 0, 'complete': 0, 'treatment': 0
        })
    return studies

@app.post("/api/upload-study")
async def upload_study(
    study_id: str = Form(...),
    files: List[UploadFile] = File(...)
):
    db = SessionLocal()
    try:
        patients_to_add = []
        samples_to_add = []
        mutations_to_add = []
        
        patient_lines = []
        sample_lines = []
        mutation_lines = []

        for file in files:
            content = await file.read()
            text_content = content.decode('utf-8').splitlines()
            if 'patient' in file.filename.lower():
                patient_lines = text_content
            elif 'sample' in file.filename.lower() and 'tumor' not in file.filename.lower():
                sample_lines = text_content
            elif 'mutation' in file.filename.lower():
                mutation_lines = text_content
                
        # Parse patients
        if patient_lines:
            header_idx = -1
            for i, line in enumerate(patient_lines):
                if not line.startswith('#') and 'PATIENT_ID' in line:
                    header_idx = i
                    break
            if header_idx != -1:
                headers = patient_lines[header_idx].strip().split('\t')
                for line in patient_lines[header_idx+1:]:
                    if not line.strip(): continue
                    cols = line.strip().split('\t')
                    row = dict(zip(headers, cols))
                    pid = get_field(row, ['PATIENT_ID'])
                    if not pid: continue
                    patients_to_add.append(models.Patient(
                        study_id=study_id,
                        patient_id=pid,
                        diagnosis=get_field(row, ['DIAGNOSIS', 'DIAGNOSIS_AT_INCLUSION', 'PRIMARY_DIAGNOSIS']),
                        stage=get_field(row, ['STAGE', 'PATHOLOGIC_STAGE']),
                        diagnosis_age=safe_float(get_field(row, ['AGE', 'DIAGNOSIS_AGE'])),
                        sex=get_field(row, ['SEX', 'GENDER']),
                        ethnicity=get_field(row, ['ETHNICITY', 'RACE', 'ETHNICITY_CATEGORY'])
                    ))
            db.bulk_save_objects(patients_to_add)
            db.commit()

        # Parse samples
        patients_map = {p.patient_id: p.id for p in db.query(models.Patient).filter(models.Patient.study_id == study_id).all()}
        if sample_lines:
            header_idx = -1
            for i, line in enumerate(sample_lines):
                if not line.startswith('#') and ('PATIENT_ID' in line or 'SAMPLE_ID' in line):
                    header_idx = i
                    break
            if header_idx != -1:
                headers = sample_lines[header_idx].strip().split('\t')
                for line in sample_lines[header_idx+1:]:
                    if not line.strip(): continue
                    cols = line.strip().split('\t')
                    row = dict(zip(headers, cols))
                    sid = get_field(row, ['SAMPLE_ID'])
                    pid = get_field(row, ['PATIENT_ID'])
                    if not sid or not pid or pid not in patients_map: continue
                    samples_to_add.append(models.Sample(
                        study_id=study_id,
                        sample_id=sid,
                        immunohistochemistry=get_field(row, ['IMMUNOHISTOCHEMISTRY', 'IHC']),
                        oncotree_code=get_field(row, ['ONCOTREE_CODE']),
                        cancer_type=get_field(row, ['CANCER_TYPE']),
                        cancer_type_detailed=get_field(row, ['CANCER_TYPE_DETAILED']),
                        somatic_status=get_field(row, ['SOMATIC_STATUS']),
                        tmb_nonsynonymous=safe_float(get_field(row, ['TMB_NONSYNONYMOUS'])),
                        patient_id=patients_map[pid]
                    ))
            db.bulk_save_objects(samples_to_add)
            db.commit()

        # Parse mutations
        samples_map = {s.sample_id: s.id for s in db.query(models.Sample).filter(models.Sample.study_id == study_id).all()}
        if mutation_lines:
            header_idx = -1
            for i, line in enumerate(mutation_lines):
                if not line.startswith('#') and 'Hugo_Symbol' in line:
                    header_idx = i
                    break
            if header_idx != -1:
                headers = [h.strip().lower() for h in mutation_lines[header_idx].strip().split('\t')]
                try:
                    hugo_idx = headers.index('hugo_symbol')
                    sample_idx = headers.index('tumor_sample_barcode')
                    for line in mutation_lines[header_idx+1:]:
                        if not line.strip(): continue
                        cols = line.strip().split('\t')
                        if len(cols) > max(hugo_idx, sample_idx):
                            hugo = cols[hugo_idx].strip()
                            sbarcode = cols[sample_idx].strip()
                            if sbarcode in samples_map:
                                mutations_to_add.append(models.Mutation(
                                    hugo_symbol=hugo,
                                    sample_id=samples_map[sbarcode],
                                    # Basic mapping for new uploads if columns exist
                                    protein_change=cols[headers.index('hgvsp_short')] if 'hgvsp_short' in headers and len(cols)>headers.index('hgvsp_short') else None,
                                    mutation_type=cols[headers.index('variant_classification')] if 'variant_classification' in headers and len(cols)>headers.index('variant_classification') else None
                                ))
                except ValueError:
                    pass
            
            if mutations_to_add:
                db.bulk_save_objects(mutations_to_add)
                db.commit()

        return {"status": "success", "message": "Study uploaded successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

