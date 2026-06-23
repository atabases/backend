import os
from typing import List
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

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

@app.get("/api/studies")
def get_studies(db: Session = Depends(get_db)):
    """
    Returns dynamic metadata and sample/mutation statistics for all studies.
    """
    # 1. Total samples per study
    sample_counts = db.query(models.Sample.study_id, func.count(models.Sample.id)).group_by(models.Sample.study_id).all()
    sample_dict = {s[0]: s[1] for s in sample_counts if s[0]}

    # 2. Samples with mutations per study
    mutation_sample_counts = (
        db.query(models.Sample.study_id, func.count(func.distinct(models.Mutation.sample_id)))
        .join(models.Mutation, models.Mutation.sample_id == models.Sample.id)
        .group_by(models.Sample.study_id)
        .all()
    )
    mutation_dict = {s[0]: s[1] for s in mutation_sample_counts if s[0]}

    # 3. Total patients per study
    patient_counts = db.query(models.Patient.study_id, func.count(models.Patient.id)).group_by(models.Patient.study_id).all()
    patient_dict = {s[0]: s[1] for s in patient_counts if s[0]}

    studies_data = {}
    all_study_ids = set(list(sample_dict.keys()) + list(mutation_dict.keys()) + list(patient_dict.keys()))
    for s_id in all_study_ids:
        studies_data[s_id] = {
            "study_id": s_id,
            "patients": patient_dict.get(s_id, 0),
            "samples": sample_dict.get(s_id, 0),
            "mutations": mutation_dict.get(s_id, 0)
        }
    return studies_data

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
            # We don't have all these columns in DB, so we mock some for the UI
            mutations.append({
                "gene": m.hugo_symbol,
                "proteinChange": "N/A",
                "annotation": "None",
                "mutationType": "Missense",
                "cohort": "N/A"
            })

    return {
        "patientId": patient.patient_id,
        "diagnosis": patient.diagnosis,
        "mutations": mutations
    }
