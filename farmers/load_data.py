import csv
from farmers.models import Scheme


def get_details(name, state):

    name_lower = name.lower()

    # DEFAULT
    description = f"{name} is a government scheme supporting farmers."
    eligibility = "Farmers eligible as per government norms."
    documents = "Aadhaar, Bank account, Land records"
    link = "https://www.myscheme.gov.in"

    # 🔥 REAL IMPORTANT SCHEMES (accurate)
    if "kisan samman" in name_lower:
        description = "₹6000 yearly financial support for farmers."
        eligibility = "Small & marginal farmers"
        documents = "Aadhaar, Bank, Land"
        link = "https://pmkisan.gov.in"

    elif "fasal bima" in name_lower:
        description = "Crop insurance scheme."
        eligibility = "All farmers"
        documents = "Aadhaar, Land"
        link = "https://pmfby.gov.in"

    elif "soil health" in name_lower:
        description = "Soil testing scheme."
        eligibility = "Farmers"
        link = "https://soilhealth.dac.gov.in"

    elif "credit card" in name_lower:
        description = "Loan support for farmers."
        eligibility = "Farmers"
        link = "https://www.myscheme.gov.in/schemes/kcc"

    return description, eligibility, documents, link


def run():

    Scheme.objects.all().delete()

    with open("schemes.csv", newline='', encoding='utf-8') as file:
        reader = csv.DictReader(file)

        for row in reader:

            # Use CSV data if available, otherwise use defaults
            desc = row.get('description', '') or get_details(row['scheme_name'], row['state'])[0]
            elig = row.get('eligibility', '') or get_details(row['scheme_name'], row['state'])[1]
            docs = row.get('documents_required', '') or get_details(row['scheme_name'], row['state'])[2]
            link = row.get('official_website', '') or get_details(row['scheme_name'], row['state'])[3]

            Scheme.objects.create(
                scheme_name=row['scheme_name'],
                scheme_type=row['scheme_type'],
                state=row['state'],
                department=row['department'],
                description=desc,
                eligibility=elig,
                documents_required=docs,
                apply_link=link,
                official_website=link,
                min_age=18,
                max_age=65,
                income_limit=500000,
                category="All"
            )

    print("✅ DATA IMPORTED SUCCESSFULLY")