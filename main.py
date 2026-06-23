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

@app.get("/api/dashboard/data")
def get_dashboard_data(db: Session = Depends(get_db)):
    """
    Returns aggregated data for all charts and tables in the dashboard grid.
    """
    # 1. Total counts
    total_patients = db.query(models.Patient).count()
    total_samples = db.query(models.Sample).count()

    # Helper for generic group by distribution
    def get_distribution(model, column):
        result = db.query(column, func.count(model.id)).group_by(column).all()
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
    samples_per_patient = db.query(models.Sample.patient_id, func.count(models.Sample.id)).group_by(models.Sample.patient_id).all()
    samples_per_patient_dist = {}
    for row in samples_per_patient:
        cnt = str(row[1])
        samples_per_patient_dist[cnt] = samples_per_patient_dist.get(cnt, 0) + 1
    samples_per_patient_chart = [{"name": k, "value": v} for k, v in samples_per_patient_dist.items()]

    # --- BAR CHARTS (Raw data arrays for frontend binning) ---
    ages = [a[0] for a in db.query(models.Patient.diagnosis_age).filter(models.Patient.diagnosis_age != None).all()]
    tmbs = [t[0] for t in db.query(models.Sample.tmb_nonsynonymous).filter(models.Sample.tmb_nonsynonymous != None).all()]
    
    muts_per_sample = db.query(models.Mutation.sample_id, func.count(models.Mutation.id)).group_by(models.Mutation.sample_id).all()
    mutation_counts = [m[1] for m in muts_per_sample]

    # --- TABLES ---
    # Top 50 Mutated Genes
    mutated_genes = db.query(models.Mutation.hugo_symbol, func.count(models.Mutation.id)).group_by(models.Mutation.hugo_symbol).order_by(func.count(models.Mutation.id).desc()).limit(50).all()
    
    # Calculate freq = (mutated samples / total samples) * 100
    # Wait, the query above counts total mutations across ALL samples. For "freq" in the screenshot,
    # we usually want % of profiled samples that have this mutation.
    # We will just pass the raw mutation count for now, and approximate freq in frontend or here.
    mutated_genes_table = []
    for m in mutated_genes:
        # Number of unique samples that have this mutation
        unique_samples = db.query(func.count(func.distinct(models.Mutation.sample_id))).filter(models.Mutation.hugo_symbol == m[0]).scalar()
        freq = round((unique_samples / total_samples) * 100, 1) if total_samples > 0 else 0
        mutated_genes_table.append({
            "gene": m[0], 
            "count": m[1],
            "freq": freq
        })

    return {
        "summary": {
            "patients": total_patients,
            "samples": total_samples
        },
        "pie": {
            "cancer_studies": [{"name": "paac_jhu_2014", "value": total_samples}],
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
                {"name": "Mutations", "count": total_samples, "freq": 100.0}
            ],
            "case_lists": [
                {"name": "All samples", "count": total_samples, "freq": 100.0},
                {"name": "Samples with mutation data", "count": len(muts_per_sample), "freq": round((len(muts_per_sample)/total_samples)*100, 1) if total_samples > 0 else 0}
            ]
        }
    }
