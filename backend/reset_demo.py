from database import SessionLocal
from models import RFP, Proposal
import os

# Delete all proposals and RFPs
with SessionLocal() as db:
    db.query(Proposal).delete()
    db.query(RFP).delete()
    db.commit()
print("All RFPs and Proposals deleted!")

# Optionally delete all generated PDFs
pdf_dir = os.path.join(os.path.dirname(__file__), '../generated_pdfs')
if os.path.exists(pdf_dir):
    for f in os.listdir(pdf_dir):
        file_path = os.path.join(pdf_dir, f)
        if os.path.isfile(file_path):
            os.remove(file_path)
print("All generated PDFs deleted!")
