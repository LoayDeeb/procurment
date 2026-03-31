import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

import openai
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import SessionLocal, init_db
from models import Proposal as ProposalModel
from models import RFP as RFPModel

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL").strip()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
PDF_DIR = BASE_DIR / "generated_pdfs"
PROPOSALS_DIR = BASE_DIR / "proposals"
PDF_DIR.mkdir(parents=True, exist_ok=True)
PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/pdfs", StaticFiles(directory=str(PDF_DIR)), name="pdfs")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.on_event("startup")
def on_startup():
    init_db()


class ChatRequest(BaseModel):
    messages: List[Dict[str, Any]]


class TTSRequest(BaseModel):
    text: str


class RFPResponse(BaseModel):
    id: int
    requirements: Optional[str] = ""
    pdf_path: Optional[str] = ""

    model_config = {"from_attributes": True}


class ProposalResponse(BaseModel):
    id: int
    rfp_id: int
    filename: str
    score: Optional[float] = None
    report: Optional[str] = None
    vendor: Optional[str] = None
    created_at: Optional[str] = None

    model_config = {"from_attributes": True}


ARABIC_DIGIT_WORDS = {
    0: "صفر",
    1: "واحد",
    2: "اثنين",
    3: "ثلاثة",
    4: "أربعة",
    5: "خمسة",
    6: "ستة",
    7: "سبعة",
    8: "ثمانية",
    9: "تسعة",
    10: "عشرة",
    11: "أحد عشر",
    12: "اثنا عشر",
    13: "ثلاثة عشر",
    14: "أربعة عشر",
    15: "خمسة عشر",
    16: "ستة عشر",
    17: "سبعة عشر",
    18: "ثمانية عشر",
    19: "تسعة عشر",
}

ARABIC_TENS_WORDS = {
    20: "عشرون",
    30: "ثلاثون",
    40: "أربعون",
    50: "خمسون",
    60: "ستون",
    70: "سبعون",
    80: "ثمانون",
    90: "تسعون",
}

EASTERN_TO_WESTERN = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def _number_to_arabic_words(n: int) -> str:
    if n < 20:
        return ARABIC_DIGIT_WORDS[n]
    if n < 100:
        tens = (n // 10) * 10
        unit = n % 10
        if unit == 0:
            return ARABIC_TENS_WORDS[tens]
        return f"{ARABIC_DIGIT_WORDS[unit]} و{ARABIC_TENS_WORDS[tens]}"
    if n < 1000:
        hundreds = n // 100
        rem = n % 100
        if hundreds == 1:
            head = "مئة"
        elif hundreds == 2:
            head = "مئتان"
        else:
            head = f"{ARABIC_DIGIT_WORDS[hundreds]}مئة"
        if rem == 0:
            return head
        return f"{head} و{_number_to_arabic_words(rem)}"
    if n < 10000:
        thousands = n // 1000
        rem = n % 1000
        if thousands == 1:
            head = "ألف"
        elif thousands == 2:
            head = "ألفان"
        elif 3 <= thousands <= 9:
            head = f"{ARABIC_DIGIT_WORDS[thousands]} آلاف"
        else:
            head = f"{_number_to_arabic_words(thousands)} ألف"
        if rem == 0:
            return head
        return f"{head} و{_number_to_arabic_words(rem)}"

    # For larger values, spell each digit to avoid showing numeric characters.
    return " ".join(ARABIC_DIGIT_WORDS[int(ch)] for ch in str(n))


def replace_numbers_with_arabic_words(text: str) -> str:
    if not text:
        return text

    def repl(match: re.Match[str]) -> str:
        raw = match.group(0)
        western = raw.translate(EASTERN_TO_WESTERN)
        try:
            n = int(western)
        except ValueError:
            return raw
        return _number_to_arabic_words(n)

    # Replace standalone numeric tokens; avoid altering numbers inside URLs/filenames.
    return re.sub(r"(?<![\w/.\-])[0-9٠-٩]+(?![\w/.\-])", repl, text)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _extract_proposal_text_from_pdf(pdf_path: Path) -> str:
    from PyPDF2 import PdfReader

    text_parts: List[str] = []

    # Primary extraction
    try:
        reader = PdfReader(str(pdf_path))
        text_parts.extend((page.extract_text() or "") for page in reader.pages)
    except Exception:
        text_parts = []

    text = "\n".join(text_parts).strip()

    # Secondary extraction for PDFs that PyPDF2 struggles with.
    if len(text) < 150:
        try:
            import pdfplumber

            with pdfplumber.open(str(pdf_path)) as pdf:
                text = "\n".join((page.extract_text() or "") for page in pdf.pages).strip()
        except Exception:
            pass

    # Optional OCR fallback for scanned PDFs if OCR deps are installed.
    if len(text) < 150:
        try:
            import pytesseract
            from pdf2image import convert_from_path

            ocr_pages = convert_from_path(str(pdf_path), dpi=220)
            ocr_text = []
            for image in ocr_pages:
                page_text = pytesseract.image_to_string(image, lang="ara+eng")
                if page_text:
                    ocr_text.append(page_text)
            joined = "\n".join(ocr_text).strip()
            if joined:
                text = joined
        except Exception:
            pass

    return text.strip()


def generate_rfp_pdf(text: str) -> str:
    filename = f"rfp_{uuid.uuid4().hex}.pdf"
    filepath = PDF_DIR / filename
    template_path = BASE_DIR / "template.html"

    try:
        from render_pdf import generate_pdf

        generate_pdf(text, str(template_path), str(filepath))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {exc}") from exc

    db = SessionLocal()
    try:
        rfp = RFPModel(name="Chatbot", pdf_filename=filename, requirements=text)
        db.add(rfp)
        db.commit()
    finally:
        db.close()

    return filename


def generate_elevenlabs_audio(text: str) -> bytes:
    if not ELEVENLABS_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="ELEVENLABS_API_KEY is not configured on backend.",
        )

    clean_text = (text or "").strip()
    if not clean_text:
        raise HTTPException(status_code=400, detail="Text is required for TTS.")

    endpoint = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}/stream?output_format=mp3_44100_128"
    payload = {
        "text": clean_text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.4, "similarity_boost": 0.75},
    }
    req = urllib_request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "xi-api-key": ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=35) as resp:
            return resp.read()
    except HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"ElevenLabs HTTP error: {exc.code}") from exc
    except URLError as exc:
        raise HTTPException(status_code=502, detail=f"ElevenLabs network error: {exc.reason}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate ElevenLabs audio: {exc}") from exc


@app.post("/chat/rfp")
def chat_rfp(req: ChatRequest):
    tools = [
        {
            "type": "function",
            "name": "generate_pdf",
            "description": "Generate a PDF from provided RFP requirements. Generate the RFP text and all content in Arabic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "RFP requirements text"},
                },
                "required": ["text"],
            },
        }
    ]

    system_prompt = (
        "You are GIG Jordan's senior procurement copilot for enterprise insurance projects.\n\n"
        "Conversation behavior:\n"
        "- Always speak in Jordanian colloquial Arabic only (لهجة أردنية عامية) unless user asks for another language.\n"
        "- Do not use Modern Standard Arabic (Fusha) in chat replies.\n"
        "- Use natural Jordanian expressions and phrasing, while keeping the message clear and respectful.\n"
        "- Keep chat replies short and conversational (2-4 lines).\n"
        "- Ask maximum three clarification questions in total.\n"
        "- If enough input is available, skip questions and move directly to drafting.\n\n"
        "RFP quality bar (mandatory):\n"
        "- Produce a board-ready, professional, real-world RFP, not a generic draft.\n"
        "- Use formal procurement language and clear acceptance criteria.\n"
        "- Include structured sections with headings:\n"
        "  1) Executive Summary\n"
        "  2) Background & Business Objectives\n"
        "  3) Scope of Work (In Scope / Out of Scope)\n"
        "  4) Functional Requirements\n"
        "  5) Technical & Integration Requirements\n"
        "  6) Security, Data Privacy, BCM/DR, and Regulatory Compliance (Jordan insurance context)\n"
        "  7) Vendor Qualifications & Mandatory Evidence\n"
        "  8) Project Governance, Timeline, Milestones, and Deliverables\n"
        "  9) Commercial Model, Pricing Template, and Assumptions\n"
        "  10) Evaluation Methodology and Weighted Scoring Matrix\n"
        "  11) Submission Instructions, Deadlines, and Validity Period\n"
        "  12) Contractual Terms, SLAs, Warranties, and Penalties\n"
        "  13) Appendices (glossary, forms, templates)\n"
        "- Include practical insurance-domain requirements for claims, underwriting, policy admin, CRM/contact center, integrations, and reporting.\n\n"
        "Formatting constraints:\n"
        "- Never output numeric digits in chat text; always write numbers as Arabic words."
    )
    input_msgs: List[Dict[str, Any]] = [
        {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]}
    ]
    for msg in req.messages:
        input_msgs.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})

    response = openai.responses.create(model="gpt-4.1", input=input_msgs, tools=tools)

    for output in response.output:
        if getattr(output, "type", None) in ("function_call", "tool_call") and getattr(output, "name", "") == "generate_pdf":
            arguments = getattr(output, "arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except Exception:
                    arguments = {}
            text = arguments.get("text") if isinstance(arguments, dict) else None
            if text:
                pdf_filename = generate_rfp_pdf(text)
                pdf_url = f"/download/{pdf_filename}"
                return {"reply": "تم تجهيز ملف طلب العروض بصيغة PDF وهو جاهز للتنزيل.", "pdf_url": pdf_url}
        elif getattr(output, "type", None) == "message":
            msg_text = ""
            for c in getattr(output, "content", []):
                if hasattr(c, "type") and c.type == "output_text":
                    msg_text += getattr(c, "text", "")
            if msg_text:
                return {"reply": replace_numbers_with_arabic_words(msg_text)}

    return {"reply": "ما وصلتني استجابة صالحة من المساعد."}


@app.post("/tts/elevenlabs")
def elevenlabs_tts(req: TTSRequest):
    audio_bytes = generate_elevenlabs_audio(req.text)
    return Response(content=audio_bytes, media_type="audio/mpeg")


@app.post("/rfps", response_model=RFPResponse)
def create_rfp(req: ChatRequest, db: Session = Depends(get_db)):
    rfp = RFPModel(requirements=json.dumps(req.messages, ensure_ascii=False), pdf_path="", name="Chatbot")
    db.add(rfp)
    db.commit()
    db.refresh(rfp)
    return rfp


@app.get("/rfps")
def list_rfps(db: Session = Depends(get_db)):
    rfps = db.query(RFPModel).all()
    result = []
    for r in rfps:
        pdf_filename = r.pdf_filename or ""
        result.append(
            {
                "id": r.id,
                "name": r.name or f"RFP {r.id}",
                "status": r.status or "-",
                "score": r.score,
                "requirements": r.requirements or "",
                "pdf_path": f"/pdfs/{pdf_filename}" if pdf_filename else "",
                "pdf_filename": pdf_filename,
                "proposal_count": db.query(ProposalModel).filter(ProposalModel.rfp_id == r.id).count(),
            }
        )
    return result


@app.get("/download/{filename}")
def download_pdf(filename: str):
    filepath = PDF_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(str(filepath), media_type="application/pdf")


@app.post("/rfps/{rfp_id}/proposals", response_model=ProposalResponse)
def upload_proposal(rfp_id: int, file: UploadFile = File(...), vendor: str = "", db: Session = Depends(get_db)):
    filepath = PROPOSALS_DIR / f"{rfp_id}_{file.filename}"
    with filepath.open("wb") as handle:
        handle.write(file.file.read())

    proposal = ProposalModel(
        rfp_id=rfp_id,
        pdf_filename=str(filepath),
        vendor=vendor or None,
        created_at=datetime.now().isoformat(timespec="seconds"),
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return {
        "id": proposal.id,
        "rfp_id": proposal.rfp_id,
        "filename": proposal.pdf_filename,
        "score": proposal.score,
        "report": proposal.report,
        "vendor": proposal.vendor,
        "created_at": proposal.created_at,
    }


@app.get("/proposals/{proposal_id}", response_model=ProposalResponse)
def get_proposal(proposal_id: int, db: Session = Depends(get_db)):
    proposal = db.query(ProposalModel).filter(ProposalModel.id == proposal_id).first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return {
        "id": proposal.id,
        "rfp_id": proposal.rfp_id,
        "filename": proposal.pdf_filename,
        "score": proposal.score,
        "report": proposal.report,
        "vendor": proposal.vendor,
        "created_at": proposal.created_at,
    }


@app.get("/proposals/{proposal_id}/download")
def download_proposal_file(proposal_id: int, db: Session = Depends(get_db)):
    proposal = db.query(ProposalModel).filter(ProposalModel.id == proposal_id).first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    filepath = Path(proposal.pdf_filename)
    if not filepath.is_absolute():
        filepath = BASE_DIR / filepath
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Proposal file not found")

    return FileResponse(str(filepath), media_type="application/pdf", filename=filepath.name)


@app.get("/rfps/{rfp_id}/proposals")
def list_proposals(rfp_id: int, db: Session = Depends(get_db)):
    proposals = (
        db.query(ProposalModel)
        .filter(ProposalModel.rfp_id == rfp_id)
        .order_by(ProposalModel.score.desc().nullslast(), ProposalModel.id.desc())
        .all()
    )

    result = []
    for p in proposals:
        file_path = Path(p.pdf_filename)
        upload_date = p.created_at
        if not upload_date and file_path.exists():
            upload_date = datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(timespec="seconds")

        result.append(
            {
                "id": p.id,
                "filename": file_path.name,
                "score": p.score,
                "report": p.report,
                "vendor": p.vendor,
                "upload_date": upload_date,
                "pdf_summary": p.pdf_summary,
            }
        )
    return result


@app.get("/proposals")
def list_all_proposals(db: Session = Depends(get_db)):
    proposals = (
        db.query(ProposalModel, RFPModel)
        .join(RFPModel, ProposalModel.rfp_id == RFPModel.id)
        .order_by(ProposalModel.created_at.desc().nullslast(), ProposalModel.id.desc())
        .all()
    )

    result = []
    for proposal, rfp in proposals:
        file_path = Path(proposal.pdf_filename)
        upload_date = proposal.created_at
        if not upload_date and file_path.exists():
            upload_date = datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(timespec="seconds")

        score = proposal.score
        status = "Scored" if score is not None else "Pending"

        result.append(
            {
                "id": proposal.id,
                "rfp_id": proposal.rfp_id,
                "rfp_name": rfp.name or f"RFP {proposal.rfp_id}",
                "vendor": proposal.vendor or "-",
                "score": score,
                "status": status,
                "report": proposal.report,
                "upload_date": upload_date,
                "filename": file_path.name,
                "pdf_summary": proposal.pdf_summary,
            }
        )

    return result


@app.post("/rfps/{rfp_id}/score")
def score_proposal(
    rfp_id: int,
    proposal_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    try:
        import PyPDF2  # noqa: F401
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PyPDF2 is required for scoring: {exc}") from exc

    filename_lower = (file.filename or "").lower()
    if not filename_lower.endswith(".pdf"):
        raise HTTPException(status_code=415, detail="Only PDF files are supported for scoring.")

    temp_path = BASE_DIR / "temp_proposal.pdf"
    with temp_path.open("wb") as handle:
        handle.write(file.file.read())

    try:
        proposal_text = _extract_proposal_text_from_pdf(temp_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    if len(proposal_text.strip()) < 150:
        raise HTTPException(
            status_code=422,
            detail=(
                "Could not extract enough readable text from the uploaded PDF. "
                "Please upload a text-based PDF (not image-only scan) or enable OCR dependencies."
            ),
        )

    rfp = db.query(RFPModel).filter(RFPModel.id == rfp_id).first()
    if not rfp or not rfp.requirements:
        raise HTTPException(status_code=404, detail="RFP or requirements not found")

    proposal = (
        db.query(ProposalModel)
        .filter(ProposalModel.id == proposal_id, ProposalModel.rfp_id == rfp_id)
        .first()
    )
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found for this RFP.")

    prompt = f"""
You are a senior procurement evaluation committee assistant for enterprise insurance procurements.
Your job is to score with high rigor and no hallucination.

Core rules:
1) Evidence-only: use only what is explicitly present in proposal text.
2) No assumption credit: if a requirement is unclear/missing, score lower and mention the gap.
3) Calibration: a "high" score requires specific, verifiable detail (not marketing language).
4) Consistency: same scoring standard across all dimensions.
5) Keep response concise and objective.

RFP Requirements:
{rfp.requirements}

Proposal:
{proposal_text}

Score dimensions (0-20 each):
- Technical: scope fit, architecture clarity, integration approach, delivery feasibility.
- Cost: pricing completeness, transparency, assumptions, lifecycle/TCO clarity.
- Compliance: legal/regulatory/security/privacy controls and auditability.
- Risk: implementation, dependency, operational and support risks (higher score = lower risk exposure).
- Experience: proven references, relevant domain work, team capability.

Deduction guidance:
- Missing mandatory section: minus 4 to 8 points in related dimension.
- Vague claims without implementation detail: minus 2 to 5 points.
- No explicit compliance/security evidence: cap Compliance at 10.
- No credible timeline/governance plan: cap Technical at 12 and Risk at 12.

Return ONLY valid JSON with this exact shape:
{{
  "vendor": "string",
  "summary": "short executive assessment",
  "scores": {{
    "Technical": number,
    "Cost": number,
    "Compliance": number,
    "Risk": number,
    "Experience": number
  }},
  "strengths": ["string", "string"],
  "risks": ["string", "string"],
  "missing_requirements": ["string", "string"],
  "confidence": number
}}

Constraints:
- numbers in scores must be numeric (not strings), between 0 and 20.
- confidence must be numeric between 0 and 1.
- no markdown, no prose outside JSON.
"""

    overall_score = 0
    report = "Scoring unavailable."
    vendor = ""
    breakdown = {}
    technical = 0
    cost = 0
    compliance = 0
    risk = 0
    experience = 0

    try:
        response = openai.chat.completions.create(
            model="gpt-4.1",
            messages=[{"role": "system", "content": prompt}],
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content.strip())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI scoring request failed: {exc}") from exc

    report = str(result.get("summary") or report)
    vendor = str(result.get("vendor") or "")
    breakdown = result.get("scores", {}) or {}

    technical = _clamp(_to_float(breakdown.get("Technical"), 0.0), 0.0, 20.0)
    cost = _clamp(_to_float(breakdown.get("Cost"), 0.0), 0.0, 20.0)
    compliance = _clamp(_to_float(breakdown.get("Compliance"), 0.0), 0.0, 20.0)
    risk = _clamp(_to_float(breakdown.get("Risk"), 0.0), 0.0, 20.0)
    experience = _clamp(_to_float(breakdown.get("Experience"), 0.0), 0.0, 20.0)

    # Deterministic weighted overall score (0-100) to reduce model variance.
    overall_score = round(
        (
            (technical * 0.30)
            + (cost * 0.20)
            + (compliance * 0.20)
            + (risk * 0.15)
            + (experience * 0.15)
        )
        * 5.0,
        1,
    )
    overall_score = _clamp(overall_score, 0.0, 100.0)
    breakdown = {
        "Technical": technical,
        "Cost": cost,
        "Compliance": compliance,
        "Risk": risk,
        "Experience": experience,
    }

    existing_vendor = (proposal.vendor or "").strip() if proposal else ""
    final_vendor = vendor
    if proposal:
        proposal.score = overall_score
        proposal.report = report
        # Always preserve explicitly provided vendor name from upload form.
        # Only use AI-extracted vendor when the record has no vendor yet.
        if (not existing_vendor) and vendor:
            proposal.vendor = vendor
        final_vendor = proposal.vendor or vendor

    try:
        from jinja2 import Template
        from score_chart import render_score_dashboard_base64
        from weasyprint import HTML

        scores = {
            "Technical": technical,
            "Cost": cost,
            "Compliance": compliance,
            "Risk": risk,
            "Experience": experience,
        }
        chart_b64 = render_score_dashboard_base64(scores, overall_score)
        rfp_name = rfp.name or f"RFP #{rfp_id}"
        proposal_date = proposal.created_at if proposal else datetime.now().isoformat(timespec="seconds")
        weighted_rows = "".join(
            f"<tr><td>{name}</td><td>{val:.1f}/20</td><td>{int(round((float(val)/20)*100))}%</td></tr>"
            for name, val in scores.items()
        )
        decision_tag = "Strong Candidate" if overall_score >= 80 else "Conditional Review" if overall_score >= 60 else "High Risk"

        html_body = f"""
<section style="border:1px solid #dbe4f6;border-radius:12px;padding:14px 16px;background:#f8fbff;margin-bottom:12px;">
  <h2 style="margin:0 0 8px 0;color:#1f3280;">Proposal Evaluation Report</h2>
  <div style="display:flex;gap:10px;flex-wrap:wrap;">
    <div style="background:#fff;border:1px solid #d9e4fa;border-radius:10px;padding:8px 12px;"><b>RFP:</b> {rfp_name}</div>
    <div style="background:#fff;border:1px solid #d9e4fa;border-radius:10px;padding:8px 12px;"><b>Vendor:</b> {final_vendor or '-'}</div>
    <div style="background:#fff;border:1px solid #d9e4fa;border-radius:10px;padding:8px 12px;"><b>Upload Date:</b> {proposal_date}</div>
    <div style="background:#fff;border:1px solid #d9e4fa;border-radius:10px;padding:8px 12px;"><b>Decision Tag:</b> {decision_tag}</div>
  </div>
</section>

<section style="border:1px solid #dbe4f6;border-radius:12px;padding:14px 16px;margin-bottom:12px;">
  <h3 style="margin:0 0 8px 0;color:#1f3280;">Executive Summary</h3>
  <p style="margin:0;color:#33426f;">{report}</p>
</section>

<section style="border:1px solid #dbe4f6;border-radius:12px;padding:14px 16px;margin-bottom:12px;">
  <h3 style="margin:0 0 10px 0;color:#1f3280;">Scoring Dashboard</h3>
  <div style="text-align:center;">
    <img src="{chart_b64}" style="width:100%;max-width:860px;border:1px solid #edf2fd;border-radius:12px;" />
  </div>
</section>

<section style="border:1px solid #dbe4f6;border-radius:12px;padding:14px 16px;margin-bottom:12px;">
  <h3 style="margin:0 0 10px 0;color:#1f3280;">Weighted Score Table</h3>
  <table style="width:100%;border-collapse:collapse;">
    <thead>
      <tr style="background:#eef4ff;color:#1f3280;">
        <th style="border:1px solid #dbe4f6;padding:8px;text-align:left;">Dimension</th>
        <th style="border:1px solid #dbe4f6;padding:8px;text-align:left;">Raw Score</th>
        <th style="border:1px solid #dbe4f6;padding:8px;text-align:left;">Normalized</th>
      </tr>
    </thead>
    <tbody>
      {weighted_rows}
    </tbody>
  </table>
  <p style="margin-top:10px;"><b>Overall Score:</b> {int(round(overall_score))}/100</p>
</section>

<section style="border:1px solid #dbe4f6;border-radius:12px;padding:14px 16px;">
  <h3 style="margin:0 0 8px 0;color:#1f3280;">Procurement Recommendation</h3>
  <p style="margin:0 0 6px 0;">- Validate commercial assumptions and pricing exclusions before final award.</p>
  <p style="margin:0 0 6px 0;">- Run a compliance check against mandatory regulatory and security controls.</p>
  <p style="margin:0;">- Confirm implementation timeline, SLA commitments, and integration dependencies in contract annexes.</p>
</section>
"""
        template_path = BASE_DIR / "template.html"
        with template_path.open("r", encoding="utf-8") as handle:
            tpl = Template(handle.read())
        html_out = tpl.render(content=html_body)

        pdf_filename = f"{rfp_id}_evaluation.pdf"
        pdf_path = PDF_DIR / pdf_filename
        HTML(string=html_out, base_url=str(BASE_DIR)).write_pdf(str(pdf_path))
        if proposal:
            proposal.pdf_summary = pdf_filename
    except Exception:
        # Do not fail scoring if PDF summary generation fails.
        pass

    db.commit()
    if proposal:
        db.refresh(proposal)

    return {"overall_score": overall_score, "scores": breakdown, "summary": report, "vendor": final_vendor}


@app.get("/rfps/{rfp_id}/reports")
def get_reports(rfp_id: int, db: Session = Depends(get_db)):
    proposals = (
        db.query(ProposalModel)
        .filter(ProposalModel.rfp_id == rfp_id)
        .order_by(ProposalModel.id.desc())
        .all()
    )
    return [
        {"proposal_id": p.id, "score": p.score, "report": p.report, "pdf_summary": p.pdf_summary}
        for p in proposals
    ]
