import os
from database import engine, SessionLocal
from models import Base, Patient, Sample, Mutation

def safe_float(val):
    try:
        return float(val)
    except ValueError:
        return None

def ingest_data():
    # 1. Reset database
    print("Dropping existing tables...")
    Base.metadata.drop_all(bind=engine)
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    base_path = r"D:\database\paac_jhu_2014\paac_jhu_2014"
    patient_file = os.path.join(base_path, "data_clinical_patient.txt")
    sample_file = os.path.join(base_path, "data_clinical_sample.txt")
    mutation_file = os.path.join(base_path, "data_mutations.txt")

    print(f"Reading {patient_file}...")
    # 2. Parse Patients
    with open(patient_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        # Find header row
        header_idx = 0
        for i, line in enumerate(lines):
            if line.startswith("PATIENT_ID"):
                header_idx = i
                break
        
        headers = lines[header_idx].strip().split('\t')
        
        for line in lines[header_idx + 1:]:
            if not line.strip(): continue
            cols = line.strip().split('\t')
            row = dict(zip(headers, cols))
            
            patient = Patient(
                patient_id=row.get("PATIENT_ID"),
                diagnosis=row.get("DIAGNOSIS"),
                stage=row.get("STAGE"),
                diagnosis_age=safe_float(row.get("AGE")),
                sex=row.get("SEX"),
                ethnicity=row.get("ETHNICITY")
            )
            db.add(patient)
    
    db.commit()
    print("Patients inserted.")

    # 3. Parse Samples
    print(f"Reading {sample_file}...")
    # Create a mapping of patient_id (string) to patient.id (int)
    patients = {p.patient_id: p.id for p in db.query(Patient).all()}
    sample_mapping = {} # sample_id (string) -> sample.id (int)

    with open(sample_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        # Find header row
        header_idx = 0
        for i, line in enumerate(lines):
            if line.startswith("PATIENT_ID"):
                header_idx = i
                break
        
        headers = lines[header_idx].strip().split('\t')
        
        for line in lines[header_idx + 1:]:
            if not line.strip(): continue
            cols = line.strip().split('\t')
            row = dict(zip(headers, cols))
            
            p_id = row.get("PATIENT_ID")
            patient_db_id = patients.get(p_id)
            if not patient_db_id:
                print(f"Warning: Patient {p_id} not found for sample {row.get('SAMPLE_ID')}")
                continue

            sample = Sample(
                sample_id=row.get("SAMPLE_ID"),
                immunohistochemistry=row.get("IMMUNOHISTOCHEMISTRY"),
                oncotree_code=row.get("ONCOTREE_CODE"),
                cancer_type=row.get("CANCER_TYPE"),
                cancer_type_detailed=row.get("CANCER_TYPE_DETAILED"),
                somatic_status=row.get("SOMATIC_STATUS"),
                tmb_nonsynonymous=safe_float(row.get("TMB_NONSYNONYMOUS")),
                patient_id=patient_db_id
            )
            db.add(sample)
    
    db.commit()
    print("Samples inserted.")

    # 4. Parse Mutations
    print(f"Reading {mutation_file}...")
    samples = {s.sample_id: s.id for s in db.query(Sample).all()}
    
    with open(mutation_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        header_idx = 0
        for i, line in enumerate(lines):
            if line.startswith("Hugo_Symbol"):
                header_idx = i
                break
        
        headers = lines[header_idx].strip().split('\t')
        hugo_idx = headers.index("Hugo_Symbol")
        sample_idx = headers.index("Tumor_Sample_Barcode")
        
        mutations = []
        for line in lines[header_idx + 1:]:
            if not line.strip(): continue
            cols = line.strip().split('\t')
            if len(cols) > max(hugo_idx, sample_idx):
                hugo = cols[hugo_idx]
                sample_barcode = cols[sample_idx]
                
                s_id = samples.get(sample_barcode)
                if s_id:
                    mutations.append(Mutation(
                        hugo_symbol=hugo,
                        sample_id=s_id
                    ))
        
        # Bulk insert for speed
        if mutations:
            db.bulk_save_objects(mutations)
            db.commit()
            print(f"Inserted {len(mutations)} mutations.")

    db.close()
    print("Database seeding complete!")

if __name__ == "__main__":
    ingest_data()
