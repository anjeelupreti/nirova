"""Seed the ICD-10 codes a Nepali hospital actually writes.

Not all of ICD-10: about two hundred codes covering most of an outpatient
morning, a ward round and an emergency shift here -- enteric fever and dengue
beside diabetes and COPD, obstetrics, the common injuries, and the mental
health presentations that are usually left uncoded. Marked `is_common`, so
they are what the picker offers before anybody types.

Idempotent: run it again after adding to the list and only the new ones
appear. A hospital's own edits to a title are kept; only missing codes are
created.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization
from apps.terminology.models import CodeSystem, DiagnosisCode

#: (code, title, chapter, keywords)
CODES = [
    # -- Infections ---------------------------------------------------------
    ("A01.0", "Typhoid fever", "Infections", "enteric fever typhoid widal"),
    ("A02.0", "Salmonella enteritis", "Infections", "food poisoning"),
    ("A06.0", "Acute amoebic dysentery", "Infections", "amoebiasis blood stool"),
    ("A09", "Gastroenteritis of infectious origin", "Infections", "loose motion diarrhoea vomiting"),
    ("A15.0", "Tuberculosis of lung, confirmed", "Infections", "tb pulmonary sputum afb"),
    ("A15.9", "Respiratory tuberculosis, unspecified", "Infections", "tb"),
    ("A16.9", "Respiratory tuberculosis, not confirmed", "Infections", "tb clinical"),
    ("A18.0", "Tuberculosis of bones and joints", "Infections", "spinal tb pott"),
    ("A27.9", "Leptospirosis", "Infections", "rat fever"),
    ("A36.9", "Diphtheria", "Infections", ""),
    ("A41.9", "Sepsis, unspecified", "Infections", "septicaemia septic shock"),
    ("A90", "Dengue fever", "Infections", "dengue"),
    ("A91", "Dengue haemorrhagic fever", "Infections", "dhf"),
    ("B01.9", "Varicella (chickenpox)", "Infections", "chicken pox"),
    ("B05.9", "Measles", "Infections", "dadura"),
    ("B15.9", "Hepatitis A", "Infections", "jaundice hepatitis"),
    ("B16.9", "Hepatitis B, acute", "Infections", "hbsag"),
    ("B18.1", "Chronic hepatitis B", "Infections", "hbsag chronic"),
    ("B18.2", "Chronic hepatitis C", "Infections", "hcv"),
    ("B19.9", "Viral hepatitis, unspecified", "Infections", "jaundice"),
    ("B20", "HIV disease", "Infections", "hiv aids"),
    ("B35.9", "Dermatophytosis (fungal skin infection)", "Infections", "ringworm fungal"),
    ("B50.9", "Plasmodium falciparum malaria", "Infections", "malaria"),
    ("B54", "Malaria, unspecified", "Infections", "malaria"),
    ("B55.9", "Leishmaniasis", "Infections", "kala azar"),
    ("B77.9", "Ascariasis", "Infections", "worms"),
    ("U07.1", "COVID-19, virus identified", "Infections", "covid corona"),
    # -- Neoplasms ----------------------------------------------------------
    ("C16.9", "Malignant neoplasm of stomach", "Neoplasms", "gastric cancer"),
    ("C18.9", "Malignant neoplasm of colon", "Neoplasms", "colon cancer"),
    ("C34.9", "Malignant neoplasm of lung", "Neoplasms", "lung cancer"),
    ("C50.9", "Malignant neoplasm of breast", "Neoplasms", "breast cancer"),
    ("C53.9", "Malignant neoplasm of cervix uteri", "Neoplasms", "cervical cancer"),
    ("C61", "Malignant neoplasm of prostate", "Neoplasms", "prostate cancer"),
    ("D50.9", "Iron deficiency anaemia", "Blood", "anaemia low haemoglobin"),
    ("D56.9", "Thalassaemia", "Blood", ""),
    ("D64.9", "Anaemia, unspecified", "Blood", "anaemia"),
    ("D69.6", "Thrombocytopenia, unspecified", "Blood", "low platelet"),
    # -- Endocrine and metabolic --------------------------------------------
    ("E03.9", "Hypothyroidism", "Endocrine", "thyroid tsh"),
    ("E05.9", "Thyrotoxicosis", "Endocrine", "hyperthyroid"),
    ("E10.9", "Type 1 diabetes mellitus", "Endocrine", "diabetes sugar"),
    ("E11.9", "Type 2 diabetes mellitus", "Endocrine", "diabetes sugar dm"),
    ("E11.2", "Type 2 diabetes with kidney complications", "Endocrine", "diabetic nephropathy"),
    ("E11.4", "Type 2 diabetes with neurological complications", "Endocrine", "diabetic neuropathy"),
    ("E14.9", "Diabetes mellitus, unspecified", "Endocrine", "diabetes sugar"),
    ("E16.2", "Hypoglycaemia", "Endocrine", "low sugar"),
    ("E44.0", "Moderate protein-energy malnutrition", "Endocrine", "malnutrition"),
    ("E66.9", "Obesity", "Endocrine", "overweight"),
    ("E78.5", "Hyperlipidaemia", "Endocrine", "cholesterol lipid"),
    ("E86", "Volume depletion (dehydration)", "Endocrine", "dehydration"),
    ("E87.6", "Hypokalaemia", "Endocrine", "low potassium"),
    # -- Mental health ------------------------------------------------------
    ("F10.2", "Alcohol dependence", "Mental health", "alcohol addiction"),
    ("F20.9", "Schizophrenia", "Mental health", ""),
    ("F31.9", "Bipolar affective disorder", "Mental health", "mania"),
    ("F32.9", "Depressive episode", "Mental health", "depression low mood"),
    ("F41.1", "Generalised anxiety disorder", "Mental health", "anxiety"),
    ("F41.9", "Anxiety disorder, unspecified", "Mental health", "anxiety"),
    ("F43.2", "Adjustment disorder", "Mental health", "stress"),
    ("F51.0", "Insomnia, non-organic", "Mental health", "sleep"),
    # -- Nervous system -----------------------------------------------------
    ("G40.9", "Epilepsy", "Nervous system", "seizure fits"),
    ("G43.9", "Migraine", "Nervous system", "headache"),
    ("G44.2", "Tension-type headache", "Nervous system", "headache"),
    ("G62.9", "Polyneuropathy", "Nervous system", "neuropathy tingling"),
    ("G80.9", "Cerebral palsy", "Nervous system", "cp"),
    ("H10.9", "Conjunctivitis", "Eye", "red eye"),
    ("H25.9", "Senile cataract", "Eye", "cataract"),
    ("H40.9", "Glaucoma", "Eye", ""),
    ("H52.4", "Presbyopia", "Eye", "reading glasses"),
    ("H66.9", "Otitis media", "Ear", "ear infection ear pain"),
    ("H81.1", "Benign paroxysmal vertigo", "Ear", "vertigo dizziness"),
    # -- Circulatory --------------------------------------------------------
    ("I10", "Essential hypertension", "Circulatory", "bp high blood pressure"),
    ("I11.9", "Hypertensive heart disease", "Circulatory", "bp heart"),
    ("I20.9", "Angina pectoris", "Circulatory", "chest pain"),
    ("I21.9", "Acute myocardial infarction", "Circulatory", "heart attack mi"),
    ("I25.9", "Chronic ischaemic heart disease", "Circulatory", "ihd"),
    ("I48.9", "Atrial fibrillation", "Circulatory", "af irregular pulse"),
    ("I50.9", "Heart failure", "Circulatory", "ccf chf"),
    ("I63.9", "Cerebral infarction (stroke)", "Circulatory", "stroke cva"),
    ("I64", "Stroke, not specified as haemorrhage or infarction", "Circulatory", "stroke cva"),
    ("I70.9", "Atherosclerosis", "Circulatory", ""),
    ("I83.9", "Varicose veins of lower extremities", "Circulatory", "varicose"),
    ("I84.9", "Haemorrhoids", "Circulatory", "piles"),
    # -- Respiratory --------------------------------------------------------
    ("J00", "Acute nasopharyngitis (common cold)", "Respiratory", "cold running nose"),
    ("J02.9", "Acute pharyngitis", "Respiratory", "sore throat"),
    ("J03.9", "Acute tonsillitis", "Respiratory", "tonsil sore throat"),
    ("J06.9", "Acute upper respiratory infection", "Respiratory", "uri cough cold"),
    ("J18.9", "Pneumonia, unspecified", "Respiratory", "chest infection"),
    ("J20.9", "Acute bronchitis", "Respiratory", "cough"),
    ("J21.9", "Acute bronchiolitis", "Respiratory", "infant wheeze"),
    ("J44.9", "Chronic obstructive pulmonary disease", "Respiratory", "copd smoker cough"),
    ("J45.9", "Asthma", "Respiratory", "wheeze breathlessness"),
    ("J46", "Status asthmaticus", "Respiratory", "severe asthma"),
    ("J90", "Pleural effusion", "Respiratory", ""),
    ("J93.9", "Pneumothorax", "Respiratory", ""),
    # -- Digestive ----------------------------------------------------------
    ("K02.9", "Dental caries", "Digestive", "tooth decay cavity"),
    ("K04.7", "Periapical abscess", "Digestive", "tooth abscess"),
    ("K05.3", "Chronic periodontitis", "Digestive", "gum disease"),
    ("K08.1", "Loss of teeth", "Digestive", "missing tooth"),
    ("K21.9", "Gastro-oesophageal reflux disease", "Digestive", "gerd acidity heartburn"),
    ("K25.9", "Gastric ulcer", "Digestive", "ulcer"),
    ("K29.7", "Gastritis, unspecified", "Digestive", "acidity gastric"),
    ("K30", "Functional dyspepsia", "Digestive", "indigestion"),
    ("K35.8", "Acute appendicitis", "Digestive", "appendix"),
    ("K40.9", "Inguinal hernia", "Digestive", "hernia"),
    ("K52.9", "Non-infective gastroenteritis", "Digestive", "loose motion"),
    ("K57.9", "Diverticular disease", "Digestive", ""),
    ("K59.0", "Constipation", "Digestive", ""),
    ("K70.3", "Alcoholic cirrhosis of liver", "Digestive", "liver cirrhosis"),
    ("K74.6", "Cirrhosis of liver", "Digestive", "cld liver"),
    ("K80.2", "Gallstones without cholecystitis", "Digestive", "gallstone"),
    ("K81.0", "Acute cholecystitis", "Digestive", "gallbladder"),
    ("K85.9", "Acute pancreatitis", "Digestive", "pancreas"),
    # -- Skin, musculoskeletal ---------------------------------------------
    ("L03.9", "Cellulitis", "Skin", "skin infection"),
    ("L20.9", "Atopic dermatitis", "Skin", "eczema"),
    ("L23.9", "Allergic contact dermatitis", "Skin", "allergy rash"),
    ("L30.9", "Dermatitis, unspecified", "Skin", "rash itching"),
    ("L40.9", "Psoriasis", "Skin", ""),
    ("L50.9", "Urticaria", "Skin", "hives allergy"),
    ("M10.9", "Gout", "Musculoskeletal", "uric acid joint pain"),
    ("M15.9", "Polyosteoarthritis", "Musculoskeletal", "joint pain"),
    ("M17.9", "Osteoarthritis of knee", "Musculoskeletal", "knee pain"),
    ("M25.5", "Pain in joint", "Musculoskeletal", "joint pain"),
    ("M54.5", "Low back pain", "Musculoskeletal", "back pain"),
    ("M54.2", "Cervicalgia (neck pain)", "Musculoskeletal", "neck pain"),
    ("M79.1", "Myalgia", "Musculoskeletal", "body ache"),
    ("M81.9", "Osteoporosis", "Musculoskeletal", ""),
    # -- Genitourinary ------------------------------------------------------
    ("N18.9", "Chronic kidney disease", "Genitourinary", "ckd kidney failure"),
    ("N17.9", "Acute kidney injury", "Genitourinary", "aki renal failure"),
    ("N20.0", "Calculus of kidney", "Genitourinary", "kidney stone"),
    ("N23", "Renal colic", "Genitourinary", "stone pain"),
    ("N30.0", "Acute cystitis", "Genitourinary", "uti burning urine"),
    ("N39.0", "Urinary tract infection", "Genitourinary", "uti"),
    ("N40", "Benign prostatic hyperplasia", "Genitourinary", "prostate bph"),
    ("N76.0", "Acute vaginitis", "Genitourinary", "discharge"),
    ("N80.9", "Endometriosis", "Genitourinary", ""),
    ("N92.0", "Heavy menstrual bleeding", "Genitourinary", "menorrhagia"),
    ("N93.9", "Abnormal uterine bleeding", "Genitourinary", "aub"),
    ("N97.9", "Female infertility", "Genitourinary", "infertility"),
    # -- Pregnancy and childbirth ------------------------------------------
    ("O14.9", "Pre-eclampsia", "Obstetrics", "pih high bp pregnancy"),
    ("O15.9", "Eclampsia", "Obstetrics", "fits pregnancy"),
    ("O21.0", "Mild hyperemesis gravidarum", "Obstetrics", "vomiting pregnancy"),
    ("O24.4", "Gestational diabetes mellitus", "Obstetrics", "gdm sugar pregnancy"),
    ("O42.9", "Premature rupture of membranes", "Obstetrics", "prom water break"),
    ("O47.9", "False labour", "Obstetrics", ""),
    ("O60.1", "Preterm labour with preterm delivery", "Obstetrics", "preterm"),
    ("O70.1", "Second degree perineal tear", "Obstetrics", "tear"),
    ("O72.1", "Postpartum haemorrhage", "Obstetrics", "pph bleeding"),
    ("O80", "Spontaneous vaginal delivery", "Obstetrics", "normal delivery svd"),
    ("O82", "Delivery by caesarean section", "Obstetrics", "lscs caesarean"),
    ("O03.9", "Spontaneous abortion", "Obstetrics", "miscarriage"),
    ("Z34.9", "Supervision of normal pregnancy", "Obstetrics", "anc antenatal checkup"),
    # -- Newborn and childhood ---------------------------------------------
    ("P07.3", "Preterm newborn", "Newborn", "premature baby"),
    ("P59.9", "Neonatal jaundice", "Newborn", "jaundice baby"),
    ("P36.9", "Bacterial sepsis of newborn", "Newborn", "neonatal sepsis"),
    ("R50.9", "Fever, unspecified", "Symptoms", "fever jworo"),
    ("R05", "Cough", "Symptoms", "cough"),
    ("R06.0", "Dyspnoea", "Symptoms", "breathlessness"),
    ("R07.4", "Chest pain, unspecified", "Symptoms", "chest pain"),
    ("R10.4", "Abdominal pain", "Symptoms", "stomach pain"),
    ("R11", "Nausea and vomiting", "Symptoms", "vomiting"),
    ("R42", "Dizziness and giddiness", "Symptoms", "dizzy"),
    ("R51", "Headache", "Symptoms", "headache"),
    ("R55", "Syncope and collapse", "Symptoms", "fainting"),
    ("R56.8", "Convulsions, unspecified", "Symptoms", "fits seizure"),
    # -- Injury and poisoning ----------------------------------------------
    ("S00.9", "Superficial injury of head", "Injury", "head injury"),
    ("S06.0", "Concussion", "Injury", "head injury"),
    ("S06.9", "Intracranial injury", "Injury", "head injury"),
    ("S42.3", "Fracture of shaft of humerus", "Injury", "fracture arm"),
    ("S52.5", "Fracture of lower end of radius", "Injury", "colles fracture wrist"),
    ("S72.0", "Fracture of neck of femur", "Injury", "hip fracture"),
    ("S82.6", "Fracture of lateral malleolus", "Injury", "ankle fracture"),
    ("S93.4", "Sprain of ankle", "Injury", "ankle sprain"),
    ("T14.9", "Injury, unspecified", "Injury", "injury trauma"),
    ("T16", "Foreign body in ear", "Injury", "foreign body"),
    ("T30.0", "Burn, unspecified", "Injury", "burn"),
    ("T63.0", "Snake venom toxicity", "Injury", "snake bite"),
    ("T60.9", "Pesticide poisoning", "Injury", "poisoning organophosphate"),
    ("T78.2", "Anaphylactic shock", "Injury", "allergy reaction"),
    ("W54", "Bitten by dog", "Injury", "dog bite rabies"),
    # -- Factors influencing health status ---------------------------------
    ("Z00.0", "General medical examination", "Health status", "checkup health check"),
    ("Z23", "Immunisation", "Health status", "vaccine"),
    ("Z30.9", "Contraceptive management", "Health status", "family planning"),
    ("Z33", "Pregnant state, incidental", "Health status", ""),
    ("Z71.3", "Dietary counselling", "Health status", "diet advice"),
    ("Z76.0", "Repeat prescription", "Health status", "refill"),
]


class Command(BaseCommand):
    help = "Seed the common ICD-10 codes into one organization's vocabulary."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="manakamana")

    def handle(self, *args, **options):
        organization = Organization.objects.filter(slug=options["slug"]).first()
        if organization is None:
            raise CommandError(f"No organization '{options['slug']}'.")

        created = 0
        with tenant_context(context_for_organization(organization)):
            for code, title, chapter, keywords in CODES:
                _, made = DiagnosisCode.objects.get_or_create(
                    system=CodeSystem.ICD10,
                    code=code,
                    defaults={
                        "title": title,
                        "chapter": chapter,
                        "keywords": keywords,
                        "is_common": True,
                    },
                )
                created += 1 if made else 0
            total = DiagnosisCode.objects.count()

        self.stdout.write(f"  {created} new, {total} codes in {organization.slug}")
