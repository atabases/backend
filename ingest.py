import os
from database import engine, SessionLocal
from models import Base, Patient, Sample, Mutation

def safe_float(val):
    try:
        return float(val)
    except (ValueError, TypeError):
        return None

def get_field(row, possible_keys):
    possible_keys_lower = [k.lower() for k in possible_keys]
    for key, val in row.items():
        if key.lower().strip() in possible_keys_lower:
            return val.strip() if val else None
    return None

def ingest_data():
    # 1. Reset database
    print("Dropping existing tables...")
    Base.metadata.drop_all(bind=engine)
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    base_dir = r"D:\database"
    studies = []
    for item in os.listdir(base_dir):
        item_path = os.path.join(base_dir, item)
        if os.path.isdir(item_path):
            inner_dir = os.path.join(item_path, item)
            patient_file = os.path.join(inner_dir, "data_clinical_patient.txt")
            if os.path.exists(patient_file):
                studies.append((item, inner_dir))
                
    print(f"Found {len(studies)} studies: {[s[0] for s in studies]}")

    for study_id, inner_dir in studies:
        print(f"\nProcessing study: {study_id}...")
        patient_file = os.path.join(inner_dir, "data_clinical_patient.txt")
        sample_file = os.path.join(inner_dir, "data_clinical_sample.txt")
        mutation_file = os.path.join(inner_dir, "data_mutations.txt")

        # --- Parse Patients ---
        print(f"  Reading patients: {patient_file}...")
        with open(patient_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            header_idx = -1
            for i, line in enumerate(lines):
                if not line.startswith("#") and "PATIENT_ID" in line:
                    header_idx = i
                    break
            if header_idx == -1:
                print(f"  Warning: Header not found in {patient_file}. Skipping patients for this study.")
                continue
            
            headers = lines[header_idx].strip().split('\t')
            for line in lines[header_idx + 1:]:
                if not line.strip(): continue
                cols = line.strip().split('\t')
                row = dict(zip(headers, cols))
                
                patient_id = get_field(row, ["PATIENT_ID"])
                if not patient_id:
                    continue
                
                patient = Patient(
                    study_id=study_id,
                    patient_id=patient_id,
                    diagnosis=get_field(row, ["DIAGNOSIS", "DIAGNOSIS_AT_INCLUSION", "PRIMARY_DIAGNOSIS"]),
                    stage=get_field(row, ["STAGE", "PATHOLOGIC_STAGE", "CLINICAL_STAGE", "TUMOR_STAGE", "AJCC_PATHOLOGIC_TUMOR_STAGE"]),
                    diagnosis_age=safe_float(get_field(row, ["AGE", "DIAGNOSIS_AGE", "AGE_AT_DIAGNOSIS"])),
                    sex=get_field(row, ["SEX", "GENDER"]),
                    ethnicity=get_field(row, ["ETHNICITY", "RACE", "ETHNICITY_CATEGORY"])
                )
                db.add(patient)
        
        db.commit()

        # Re-fetch patient mapping for this study to map samples
        patients_map = {p.patient_id: p.id for p in db.query(Patient).filter(Patient.study_id == study_id).all()}

        # --- Parse Samples ---
        if os.path.exists(sample_file):
            print(f"  Reading samples: {sample_file}...")
            with open(sample_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                header_idx = -1
                for i, line in enumerate(lines):
                    if not line.startswith("#") and ("PATIENT_ID" in line or "SAMPLE_ID" in line):
                        header_idx = i
                        break
                if header_idx == -1:
                    print(f"  Warning: Header not found in {sample_file}. Skipping samples.")
                else:
                    headers = lines[header_idx].strip().split('\t')
                    for line in lines[header_idx + 1:]:
                        if not line.strip(): continue
                        cols = line.strip().split('\t')
                        row = dict(zip(headers, cols))
                        
                        sample_id = get_field(row, ["SAMPLE_ID"])
                        if not sample_id:
                            continue
                        
                        p_id = get_field(row, ["PATIENT_ID"])
                        patient_db_id = patients_map.get(p_id)
                        if not patient_db_id:
                            continue

                        sample = Sample(
                            study_id=study_id,
                            sample_id=sample_id,
                            immunohistochemistry=get_field(row, ["IMMUNOHISTOCHEMISTRY", "IHC"]),
                            oncotree_code=get_field(row, ["ONCOTREE_CODE"]),
                            cancer_type=get_field(row, ["CANCER_TYPE"]),
                            cancer_type_detailed=get_field(row, ["CANCER_TYPE_DETAILED"]),
                            somatic_status=get_field(row, ["SOMATIC_STATUS"]),
                            tmb_nonsynonymous=safe_float(get_field(row, ["TMB_NONSYNONYMOUS"])),
                            patient_id=patient_db_id
                        )
                        db.add(sample)
            db.commit()

        # Re-fetch sample mapping for this study to map mutations
        samples_map = {s.sample_id: s.id for s in db.query(Sample).filter(Sample.study_id == study_id).all()}

        # --- Parse Mutations ---
        if os.path.exists(mutation_file):
            print(f"  Reading mutations: {mutation_file}...")
            with open(mutation_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                header_idx = -1
                for i, line in enumerate(lines):
                    if not line.startswith("#") and "Hugo_Symbol" in line:
                        header_idx = i
                        break
                
                if header_idx == -1:
                    print(f"  Warning: Header not found in {mutation_file}. Skipping mutations.")
                else:
                    headers = [h.strip().lower() for h in lines[header_idx].strip().split('\t')]
                    try:
                        hugo_idx = headers.index("hugo_symbol")
                    except ValueError:
                        hugo_idx = -1
                    try:
                        sample_idx = headers.index("tumor_sample_barcode")
                    except ValueError:
                        sample_idx = -1
                    
                    if hugo_idx != -1 and sample_idx != -1:
                        mutations = []
                        for line in lines[header_idx + 1:]:
                            if not line.strip(): continue
                            cols = line.strip().split('\t')
                            if len(cols) > max(hugo_idx, sample_idx):
                                hugo = cols[hugo_idx].strip()
                                sample_barcode = cols[sample_idx].strip()
                                
                                s_id = samples_map.get(sample_barcode)
                                if s_id:
                                    mutations.append(Mutation(
                                        hugo_symbol=hugo,
                                        sample_id=s_id
                                    ))
                        
                        # Bulk insert for speed
                        if mutations:
                            db.bulk_save_objects(mutations)
                            db.commit()
                            print(f"  Inserted {len(mutations)} mutations.")

    db.close()
    print("\nDatabase seeding complete!")

if __name__ == "__main__":
    ingest_data()
