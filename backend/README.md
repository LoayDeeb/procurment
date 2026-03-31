# Procurement AI Agent Backend (FastAPI)

This backend powers your procurement agent platform. It integrates with OpenAI GPT-4.1, handles RFP creation, PDF export, proposal uploads, scoring, and report generation.

## Features
- Conversational RFP requirements gathering via OpenAI GPT-4.1
- RFP PDF generation
- Table of all RFPs
- Proposal upload per RFP
- Automated proposal scoring and report generation (AI agent)

## Stack
- Python 3.10+
- FastAPI
- PostgreSQL (or SQLite for dev)
- OpenAI API
- PDFKit/WeasyPrint for PDF

## Quickstart
1. `pip install -r requirements.txt`
2. `uvicorn main:app --reload`

---

## Endpoints
- `POST /chat/rfp` - Start/continue RFP requirements chat
- `POST /rfps` - Save new RFP, generate PDF
- `GET /rfps` - List RFPs
- `GET /rfps/{rfp_id}/pdf` - Download RFP PDF
- `POST /rfps/{rfp_id}/proposals` - Upload proposal
- `POST /rfps/{rfp_id}/score` - Score proposal, generate report
- `GET /rfps/{rfp_id}/reports` - List/download reports

---

## .env Example
```
OPENAI_API_KEY=sk-...
DATABASE_URL=sqlite:///./test.db
```

---

## To Do
- Add authentication
- Connect to frontend
- Add cloud file storage (S3)
