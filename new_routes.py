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
