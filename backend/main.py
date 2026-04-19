import json
import logging
import os
import re
import smtplib
import threading
import time
import uuid
from datetime import datetime
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import make_msgid
from imaplib import IMAP4_SSL
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
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session, joinedload

try:
    from .database import SessionLocal, init_db
    from .models import (
        Proposal as ProposalModel,
        RFP as RFPModel,
        RfpWorkflowRequest as RfpWorkflowRequestModel,
        StakeholderRequest as StakeholderRequestModel,
    )
except ImportError:
    from database import SessionLocal, init_db
    from models import (
        Proposal as ProposalModel,
        RFP as RFPModel,
        RfpWorkflowRequest as RfpWorkflowRequestModel,
        StakeholderRequest as StakeholderRequestModel,
    )

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL").strip()
PUBLIC_BACKEND_URL = os.getenv("PUBLIC_BACKEND_URL", "http://localhost:8000").rstrip("/")
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "").strip()
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").strip()
GMAIL_SMTP_HOST = os.getenv("GMAIL_SMTP_HOST", "smtp.gmail.com").strip()
GMAIL_SMTP_PORT = int(os.getenv("GMAIL_SMTP_PORT", "465"))
GMAIL_IMAP_HOST = os.getenv("GMAIL_IMAP_HOST", "imap.gmail.com").strip()
EMAIL_POLL_SECONDS = max(int(os.getenv("EMAIL_POLL_SECONDS", "60") or "60"), 15)

WORKFLOW_STATUS_DRAFTING = "drafting"
WORKFLOW_STATUS_AWAITING = "awaiting_stakeholders"
WORKFLOW_STATUS_ALL_REPLIES = "all_replies_received"
WORKFLOW_STATUS_FINAL_READY = "final_rfp_generated"
WORKFLOW_STATUS_DELIVERED = "delivered"

STAKEHOLDER_STATUS_PENDING = "pending"
STAKEHOLDER_STATUS_REQUESTED = "requested"
STAKEHOLDER_STATUS_RECEIVED = "received"

WORKFLOW_TOKEN_PATTERN = re.compile(r"\[RFP-REQ-(\d+)-(\d+)\]")
REPLY_CUTOFF_PATTERNS = (
    re.compile(r"^On .+wrote:$", re.IGNORECASE),
    re.compile(r"^From:\s", re.IGNORECASE),
    re.compile(r"^Sent:\s", re.IGNORECASE),
    re.compile(r"^Subject:\s", re.IGNORECASE),
)


def _load_system_stakeholders() -> List[Dict[str, str]]:
    raw = os.getenv("SYSTEM_STAKEHOLDERS_JSON", "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    stakeholders: List[Dict[str, str]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        name = str(item.get("name") or role or "").strip()
        email = str(item.get("email") or "").strip()
        if role and email:
            stakeholders.append({"role": role, "name": name or role, "email": email})
    return stakeholders


SYSTEM_STAKEHOLDERS = _load_system_stakeholders()
DEFAULT_REQUESTER_NAME = os.getenv("DEFAULT_REQUESTER_NAME", "Procurement Officer").strip()
DEFAULT_REQUESTER_EMAIL = os.getenv("DEFAULT_REQUESTER_EMAIL", "").strip()


def _parse_allowed_origins() -> List[str]:
    raw = (os.getenv("CORS_ALLOWED_ORIGINS") or "").strip()
    if not raw:
        return [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    return [o.strip() for o in raw.split(",") if o.strip()]


ALLOWED_ORIGINS = _parse_allowed_origins()
ALLOW_CREDENTIALS = "*" not in ALLOWED_ORIGINS

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
PDF_DIR = BASE_DIR / "generated_pdfs"
PROPOSALS_DIR = BASE_DIR / "proposals"
PDF_DIR.mkdir(parents=True, exist_ok=True)
PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/pdfs", StaticFiles(directory=str(PDF_DIR)), name="pdfs")

_workflow_thread_started = False
logger = logging.getLogger("procurement_backend")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

WORKFLOW_SENT_REPLY = (
    "تمام، أرسلت الآن رسائل جمع المتطلبات للجهات المعنية المعروفة عندي، "
    "وبمجرد ما يصلني ردهم كلهم سأجهز نسخة RFP النهائية وأرسلها إليك."
)


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.on_event("startup")
def on_startup():
    global _workflow_thread_started
    init_db()
    logger.info(
        "startup config workflow_ready=%s requester_email=%s stakeholder_count=%s gmail_configured=%s public_backend_url=%s",
        _workflow_mode_enabled(),
        bool(DEFAULT_REQUESTER_EMAIL),
        len(SYSTEM_STAKEHOLDERS),
        bool(GMAIL_ADDRESS and GMAIL_APP_PASSWORD),
        PUBLIC_BACKEND_URL,
    )
    if not _workflow_thread_started:
        thread = threading.Thread(target=_workflow_poll_loop, daemon=True, name="workflow-email-poller")
        thread.start()
        _workflow_thread_started = True


class ChatRequest(BaseModel):
    messages: List[Dict[str, Any]]


class TTSRequest(BaseModel):
    text: str


class StakeholderInput(BaseModel):
    role: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    email: EmailStr


class WorkflowCreateRequest(BaseModel):
    requester_name: str = Field(..., min_length=1)
    requester_email: EmailStr
    title: Optional[str] = None
    messages: List[Dict[str, Any]]
    stakeholders: List[StakeholderInput]


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


def _decode_header_value(value: str) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _extract_message_text(msg: EmailMessage) -> str:
    if msg.is_multipart():
        parts: List[str] = []
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get_content_disposition() == "attachment":
                continue
            if part.get_content_type() == "text/plain":
                try:
                    parts.append(part.get_content())
                except Exception:
                    payload = part.get_payload(decode=True) or b""
                    parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="ignore"))
        return "\n".join(p for p in parts if p).strip()
    try:
        return msg.get_content().strip()
    except Exception:
        payload = msg.get_payload(decode=True) or b""
        return payload.decode(msg.get_content_charset() or "utf-8", errors="ignore").strip()


def _clean_email_reply(text: str) -> str:
    lines = text.splitlines()
    clean_lines: List[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(">"):
            break
        if any(pattern.match(stripped) for pattern in REPLY_CUTOFF_PATTERNS):
            break
        clean_lines.append(line)
    clean = "\n".join(clean_lines).strip()
    return clean or text.strip()


def _normalize_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    for msg in messages:
        role = str(msg.get("role") or "user")
        content = msg.get("content") or ""
        if isinstance(content, list):
            chunks = []
            for item in content:
                if isinstance(item, dict):
                    chunks.append(str(item.get("text") or ""))
                else:
                    chunks.append(str(item))
            text = "\n".join(chunk for chunk in chunks if chunk).strip()
        else:
            text = str(content)
        normalized.append({"role": role, "content": text})
    return normalized


def _ensure_openai_configured():
    if not openai.api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured on backend.")


def _ensure_email_configured():
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        raise HTTPException(
            status_code=503,
            detail="GMAIL_ADDRESS and GMAIL_APP_PASSWORD must be configured for stakeholder workflow.",
        )


def _workflow_mode_enabled() -> bool:
    return bool(
        DEFAULT_REQUESTER_EMAIL
        and SYSTEM_STAKEHOLDERS
        and GMAIL_ADDRESS
        and GMAIL_APP_PASSWORD
    )


def _messages_to_transcript(messages: List[Dict[str, str]]) -> str:
    lines = []
    for message in messages:
        role = "Requester" if message["role"] == "user" else "Assistant"
        content = message["content"].strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines).strip()


def _summarize_requester_brief(messages: List[Dict[str, str]]) -> str:
    transcript = _messages_to_transcript(messages)
    if not transcript:
        return "No requester briefing was provided."
    try:
        _ensure_openai_configured()
        response = openai.responses.create(
            model="gpt-4.1",
            input=[
                {
                    "role": "system",
                    "content": (
                        "Summarize a procurement request for stakeholder outreach. "
                        "Return a concise English summary with bullet-style prose that captures business goal, scope, constraints, "
                        "timeline, and open questions. Do not invent requirements."
                    ),
                },
                {"role": "user", "content": transcript},
            ],
        )
        summary = getattr(response, "output_text", "").strip()
        if summary:
            return summary
    except Exception:
        pass
    user_messages = [m["content"] for m in messages if m["role"] == "user" and m["content"].strip()]
    fallback = "\n".join(user_messages[-6:]).strip()
    return fallback[:2500] if fallback else transcript[:2500]


def _generate_final_rfp_text(workflow: RfpWorkflowRequestModel) -> str:
    _ensure_openai_configured()
    normalized_messages = json.loads(workflow.initial_messages)
    transcript = _messages_to_transcript(normalized_messages)
    stakeholder_sections = []
    for stakeholder in workflow.stakeholders:
        stakeholder_sections.append(
            "\n".join(
                [
                    f"Role: {stakeholder.role}",
                    f"Name: {stakeholder.name}",
                    f"Email: {stakeholder.email}",
                    "Requirements:",
                    stakeholder.extracted_requirements or stakeholder.reply_excerpt or "No explicit requirements captured.",
                ]
            )
        )
    stakeholder_context = "\n\n".join(stakeholder_sections)

    system_prompt = (
        "You are SASO's senior procurement copilot for standards, metrology, quality, regulatory, and digital transformation procurements.\n"
        "Produce a formal, board-ready RFP in Arabic. The final output must be the RFP document text only.\n"
        "Use structured headings and include these sections:\n"
        "1) Executive Summary\n"
        "2) Background & Business Objectives\n"
        "3) Scope of Work (In Scope / Out of Scope)\n"
        "4) Functional Requirements\n"
        "5) Technical & Integration Requirements\n"
        "6) Security, Data Privacy, BCM/DR, and Regulatory Compliance (Saudi public-sector and regulatory context)\n"
        "7) Vendor Qualifications & Mandatory Evidence\n"
        "8) Project Governance, Timeline, Milestones, and Deliverables\n"
        "9) Commercial Model, Pricing Template, and Assumptions\n"
        "10) Evaluation Methodology and Weighted Scoring Matrix\n"
        "11) Submission Instructions, Deadlines, and Validity Period\n"
        "12) Contractual Terms, SLAs, Warranties, and Penalties\n"
        "13) Appendices (glossary, forms, templates)\n"
        "Merge the requester brief and all stakeholder requirements into one coherent draft. "
        "If stakeholders disagree, reconcile them conservatively in favor of enterprise governance and note assumptions inline."
    )
    user_prompt = (
        f"Requester name: {workflow.requester_name}\n"
        f"Workflow summary:\n{workflow.initial_summary or ''}\n\n"
        f"Requester conversation transcript:\n{transcript}\n\n"
        f"Stakeholder inputs:\n{stakeholder_context}\n"
    )

    response = openai.responses.create(
        model="gpt-4.1",
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    text = getattr(response, "output_text", "").strip()
    if not text:
        raise HTTPException(status_code=502, detail="AI did not return a final RFP document.")
    return text


def _generate_rfp_pdf_file(text: str) -> str:
    filename = f"rfp_{uuid.uuid4().hex}.pdf"
    filepath = PDF_DIR / filename
    template_path = BASE_DIR / "template.html"
    try:
        from render_pdf import generate_pdf

        generate_pdf(text, str(template_path), str(filepath))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {exc}") from exc
    return filename


def _persist_rfp_document(db: Session, text: str, name: str) -> RFPModel:
    filename = _generate_rfp_pdf_file(text)
    rfp = RFPModel(name=name, pdf_filename=filename, requirements=text, pdf_path=f"/pdfs/{filename}")
    db.add(rfp)
    db.commit()
    db.refresh(rfp)
    return rfp


def generate_rfp_pdf(text: str) -> str:
    db = SessionLocal()
    try:
        rfp = _persist_rfp_document(db, text=text, name="Chatbot")
        return rfp.pdf_filename
    finally:
        db.close()


def _send_email(to_address: str, subject: str, body: str, extra_headers: Optional[Dict[str, str]] = None) -> str:
    _ensure_email_configured()
    message = EmailMessage()
    message["From"] = GMAIL_ADDRESS
    message["To"] = to_address
    message["Subject"] = subject
    message["Message-ID"] = make_msgid(domain=GMAIL_ADDRESS.split("@")[-1] if "@" in GMAIL_ADDRESS else None)
    if extra_headers:
        for key, value in extra_headers.items():
            message[key] = value
    message.set_content(body)

    with smtplib.SMTP_SSL(GMAIL_SMTP_HOST, GMAIL_SMTP_PORT, timeout=30) as smtp:
        smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        smtp.send_message(message)
    return str(message["Message-ID"])


def _build_stakeholder_email(workflow: RfpWorkflowRequestModel, stakeholder: StakeholderRequestModel) -> Dict[str, str]:
    token = f"[RFP-REQ-{workflow.id}-{stakeholder.id}]"
    subject = f"{token} Input needed for {workflow.title}"
    body = "\n".join(
        [
            f"Hello {stakeholder.name},",
            "",
            f"{workflow.requester_name} has started a procurement RFP workflow and needs your requirements as {stakeholder.role}.",
            "",
            "Request summary:",
            workflow.initial_summary or "No summary available.",
            "",
            "Please reply to this email with your requirements, constraints, approvals, risks, and any mandatory conditions that should appear in the final RFP.",
            "Reply directly in this thread so the procurement workflow can match your response automatically.",
            "",
            f"Tracking token: {token}",
            "",
            "Thank you.",
        ]
    )
    return {"subject": subject, "body": body}


def _send_stakeholder_requests(
    db: Session,
    workflow: RfpWorkflowRequestModel,
    custom_emails: Optional[List[Dict[str, str]]] = None,
):
    custom_by_role = {}
    for item in custom_emails or []:
        role = str(item.get("role") or "").strip().lower()
        if role:
            custom_by_role[role] = item
    for stakeholder in workflow.stakeholders:
        if stakeholder.status == STAKEHOLDER_STATUS_RECEIVED:
            continue
        custom_email = custom_by_role.get((stakeholder.role or "").strip().lower())
        email_content = {
            "subject": str(custom_email.get("subject") or "").strip(),
            "body": str(custom_email.get("body") or "").strip(),
        } if custom_email else _build_stakeholder_email(workflow, stakeholder)
        if not email_content["subject"] or not email_content["body"]:
            email_content = _build_stakeholder_email(workflow, stakeholder)
        outbound_message_id = _send_email(
            to_address=stakeholder.email,
            subject=email_content["subject"],
            body=email_content["body"],
        )
        stakeholder.outbound_subject = email_content["subject"]
        stakeholder.outbound_message_id = outbound_message_id
        stakeholder.status = STAKEHOLDER_STATUS_REQUESTED
        stakeholder.updated_at = now_iso()
    workflow.workflow_status = WORKFLOW_STATUS_AWAITING
    workflow.updated_at = now_iso()
    workflow.last_error = None
    db.commit()


def _build_requester_delivery_email(workflow: RfpWorkflowRequestModel) -> Dict[str, str]:
    download_url = f"{PUBLIC_BACKEND_URL}/download/{workflow.final_pdf_filename}"
    subject = f"Final RFP ready for {workflow.title}"
    body = "\n".join(
        [
            f"Hello {workflow.requester_name},",
            "",
            "Your stakeholder requirements have been collected and the final RFP draft is ready.",
            f"Workflow ID: {workflow.id}",
            f"PDF download: {download_url}",
            "",
            "A copy is also available in the procurement application.",
            "",
            "Regards,",
            "Procurement Copilot",
        ]
    )
    return {"subject": subject, "body": body}


def _serialize_stakeholder(stakeholder: StakeholderRequestModel) -> Dict[str, Any]:
    return {
        "id": stakeholder.id,
        "role": stakeholder.role,
        "name": stakeholder.name,
        "email": stakeholder.email,
        "status": stakeholder.status,
        "reply_excerpt": stakeholder.reply_excerpt,
        "extracted_requirements": stakeholder.extracted_requirements,
        "replied_at": stakeholder.replied_at,
    }


def _serialize_workflow(workflow: RfpWorkflowRequestModel) -> Dict[str, Any]:
    final_pdf_url = f"/download/{workflow.final_pdf_filename}" if workflow.final_pdf_filename else ""
    return {
        "id": workflow.id,
        "title": workflow.title,
        "requester_name": workflow.requester_name,
        "requester_email": workflow.requester_email,
        "workflow_status": workflow.workflow_status,
        "initial_summary": workflow.initial_summary,
        "final_rfp_text": workflow.final_rfp_text,
        "final_pdf_filename": workflow.final_pdf_filename,
        "final_pdf_url": final_pdf_url,
        "final_rfp_id": workflow.final_rfp_id,
        "created_at": workflow.created_at,
        "updated_at": workflow.updated_at,
        "delivered_at": workflow.delivered_at,
        "last_error": workflow.last_error,
        "stakeholders": [_serialize_stakeholder(stakeholder) for stakeholder in workflow.stakeholders],
    }


def _system_stakeholders_prompt_block() -> str:
    if not SYSTEM_STAKEHOLDERS:
        return "No stakeholder directory is configured."
    lines = []
    for item in SYSTEM_STAKEHOLDERS:
        lines.append(f'- {item["role"]}: {item["name"]} <{item["email"]}>')
    return "\n".join(lines)


def _default_requester_prompt_block() -> str:
    if DEFAULT_REQUESTER_EMAIL:
        return f"{DEFAULT_REQUESTER_NAME} <{DEFAULT_REQUESTER_EMAIL}>"
    return f"{DEFAULT_REQUESTER_NAME} <not configured>"


def _create_workflow_record(
    db: Session,
    requester_name: str,
    requester_email: str,
    title: str,
    normalized_messages: List[Dict[str, str]],
    stakeholders: List[Dict[str, str]],
) -> RfpWorkflowRequestModel:
    summary = _summarize_requester_brief(normalized_messages)
    timestamp = now_iso()
    workflow = RfpWorkflowRequestModel(
        requester_name=requester_name.strip(),
        requester_email=requester_email.strip(),
        title=title.strip(),
        initial_messages=json.dumps(normalized_messages, ensure_ascii=False),
        initial_summary=summary,
        workflow_status=WORKFLOW_STATUS_DRAFTING,
        created_at=timestamp,
        updated_at=timestamp,
    )
    db.add(workflow)
    db.flush()

    for stakeholder in stakeholders:
        db.add(
            StakeholderRequestModel(
                workflow_request_id=workflow.id,
                role=stakeholder["role"].strip(),
                name=(stakeholder.get("name") or stakeholder["role"]).strip(),
                email=stakeholder["email"].strip(),
                status=STAKEHOLDER_STATUS_PENDING,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
    db.commit()
    return (
        db.query(RfpWorkflowRequestModel)
        .options(joinedload(RfpWorkflowRequestModel.stakeholders))
        .filter(RfpWorkflowRequestModel.id == workflow.id)
        .first()
    )


def _all_stakeholders_replied(workflow: RfpWorkflowRequestModel) -> bool:
    return bool(workflow.stakeholders) and all(
        stakeholder.status == STAKEHOLDER_STATUS_RECEIVED for stakeholder in workflow.stakeholders
    )


def _match_stakeholder_by_email_headers(
    db: Session,
    in_reply_to: str,
    references: str,
) -> Optional[StakeholderRequestModel]:
    for header_value in (in_reply_to, references):
        header_value = header_value or ""
        if not header_value:
            continue
        stakeholders = (
            db.query(StakeholderRequestModel)
            .options(joinedload(StakeholderRequestModel.workflow))
            .filter(StakeholderRequestModel.outbound_message_id.isnot(None))
            .all()
        )
        for candidate in stakeholders:
            outbound_id = candidate.outbound_message_id or ""
            if outbound_id and outbound_id in header_value:
                return candidate
    return None


def _match_stakeholder_by_token(db: Session, subject: str, body: str) -> Optional[StakeholderRequestModel]:
    haystack = "\n".join([subject or "", body or ""])
    match = WORKFLOW_TOKEN_PATTERN.search(haystack)
    if not match:
        return None
    workflow_id = int(match.group(1))
    stakeholder_id = int(match.group(2))
    return (
        db.query(StakeholderRequestModel)
        .options(joinedload(StakeholderRequestModel.workflow))
        .filter(
            StakeholderRequestModel.id == stakeholder_id,
            StakeholderRequestModel.workflow_request_id == workflow_id,
        )
        .first()
    )


def _process_incoming_email_message(db: Session, msg: EmailMessage) -> bool:
    subject = _decode_header_value(msg.get("Subject", ""))
    in_reply_to = msg.get("In-Reply-To", "") or ""
    references = msg.get("References", "") or ""
    message_id = msg.get("Message-ID", "") or ""
    body = _clean_email_reply(_extract_message_text(msg))

    stakeholder = _match_stakeholder_by_email_headers(db, in_reply_to, references)
    if not stakeholder:
        stakeholder = _match_stakeholder_by_token(db, subject, body)
    if not stakeholder:
        return False

    workflow = stakeholder.workflow
    if not workflow:
        return False

    changed = False
    if stakeholder.status != STAKEHOLDER_STATUS_RECEIVED:
        stakeholder.status = STAKEHOLDER_STATUS_RECEIVED
        stakeholder.reply_message_id = message_id or stakeholder.reply_message_id
        stakeholder.reply_excerpt = body[:1200] if body else stakeholder.reply_excerpt
        stakeholder.extracted_requirements = body[:6000] if body else stakeholder.extracted_requirements
        stakeholder.replied_at = now_iso()
        stakeholder.updated_at = now_iso()
        workflow.updated_at = now_iso()
        workflow.last_error = None
        changed = True

    if _all_stakeholders_replied(workflow) and workflow.workflow_status == WORKFLOW_STATUS_AWAITING:
        workflow.workflow_status = WORKFLOW_STATUS_ALL_REPLIES
        workflow.updated_at = now_iso()
        changed = True

    if changed:
        db.commit()
    return True


def _poll_gmail_replies(db: Session) -> int:
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        return 0

    processed = 0
    mailbox = IMAP4_SSL(GMAIL_IMAP_HOST)
    try:
        mailbox.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        mailbox.select("INBOX")
        status, search_data = mailbox.search(None, "UNSEEN")
        if status != "OK":
            return 0
        for num in search_data[0].split():
            fetch_status, msg_data = mailbox.fetch(num, "(RFC822)")
            if fetch_status != "OK" or not msg_data:
                continue
            message_bytes = None
            for item in msg_data:
                if isinstance(item, tuple) and len(item) >= 2:
                    message_bytes = item[1]
                    break
            if not message_bytes:
                continue
            msg = BytesParser(policy=policy.default).parsebytes(message_bytes)
            matched = _process_incoming_email_message(db, msg)
            if matched:
                processed += 1
            mailbox.store(num, "+FLAGS", "\\Seen")
    finally:
        try:
            mailbox.close()
        except Exception:
            pass
        try:
            mailbox.logout()
        except Exception:
            pass
    return processed


def _deliver_final_rfp_if_needed(db: Session, workflow: RfpWorkflowRequestModel):
    if not workflow.final_pdf_filename:
        return
    if workflow.workflow_status == WORKFLOW_STATUS_DELIVERED:
        return
    email_content = _build_requester_delivery_email(workflow)
    _send_email(
        to_address=workflow.requester_email,
        subject=email_content["subject"],
        body=email_content["body"],
    )
    workflow.workflow_status = WORKFLOW_STATUS_DELIVERED
    workflow.delivered_at = now_iso()
    workflow.updated_at = now_iso()
    workflow.last_error = None
    db.commit()


def _finalize_ready_workflows(db: Session, workflow_id: Optional[int] = None) -> int:
    query = db.query(RfpWorkflowRequestModel).options(joinedload(RfpWorkflowRequestModel.stakeholders))
    if workflow_id is not None:
        query = query.filter(RfpWorkflowRequestModel.id == workflow_id)
    workflows = query.all()
    completed = 0
    for workflow in workflows:
        if workflow.workflow_status in (WORKFLOW_STATUS_DRAFTING, WORKFLOW_STATUS_AWAITING) and _all_stakeholders_replied(workflow):
            workflow.workflow_status = WORKFLOW_STATUS_ALL_REPLIES
            workflow.updated_at = now_iso()
            db.commit()

        if workflow.workflow_status == WORKFLOW_STATUS_ALL_REPLIES and not workflow.final_rfp_id:
            try:
                final_text = _generate_final_rfp_text(workflow)
                rfp = _persist_rfp_document(db, text=final_text, name=workflow.title)
                workflow.final_rfp_text = final_text
                workflow.final_pdf_filename = rfp.pdf_filename
                workflow.final_rfp_id = rfp.id
                workflow.workflow_status = WORKFLOW_STATUS_FINAL_READY
                workflow.updated_at = now_iso()
                workflow.last_error = None
                db.commit()
                completed += 1
            except Exception as exc:
                workflow.last_error = f"Final RFP generation failed: {exc}"
                workflow.updated_at = now_iso()
                db.commit()

        if workflow.workflow_status == WORKFLOW_STATUS_FINAL_READY and workflow.final_pdf_filename:
            try:
                _deliver_final_rfp_if_needed(db, workflow)
            except Exception as exc:
                workflow.last_error = f"Requester email delivery failed: {exc}"
                workflow.updated_at = now_iso()
                db.commit()
    return completed


def _workflow_poll_loop():
    while True:
        db = SessionLocal()
        try:
            processed = _poll_gmail_replies(db)
            finalized = _finalize_ready_workflows(db)
            if processed or finalized:
                logger.info("workflow poll processed_replies=%s finalized_workflows=%s", processed, finalized)
        except Exception as exc:
            logger.exception("workflow-email-poller failed: %s", exc)
        finally:
            db.close()
        time.sleep(EMAIL_POLL_SECONDS)


def _extract_proposal_text_from_pdf(pdf_path: Path) -> str:
    from PyPDF2 import PdfReader

    text_parts: List[str] = []
    try:
        reader = PdfReader(str(pdf_path))
        text_parts.extend((page.extract_text() or "") for page in reader.pages)
    except Exception:
        text_parts = []

    text = "\n".join(text_parts).strip()

    if len(text) < 150:
        try:
            import pdfplumber

            with pdfplumber.open(str(pdf_path)) as pdf:
                text = "\n".join((page.extract_text() or "") for page in pdf.pages).strip()
        except Exception:
            pass

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
    _ensure_openai_configured()
    workflow_mode = _workflow_mode_enabled()
    tools: List[Dict[str, Any]] = []
    if not workflow_mode:
        tools.append(
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
        )
    if workflow_mode:
        tools.append({
            "type": "function",
            "name": "start_stakeholder_workflow",
            "description": "Send stakeholder requirement emails using the fixed stakeholder directory configured for this procurement assistant. You must write a tailored subject and body for each stakeholder.",
            "parameters": {
                "type": "object",
                        "properties": {
                    "requester_name": {"type": "string", "description": "Name of the requesting user. Use the configured default requester if no override is needed."},
                    "requester_email": {"type": "string", "description": "Email of the requesting user. Use the configured default requester email if no override is needed."},
                    "title": {"type": "string", "description": "Short title for the RFP workflow"},
                    "stakeholder_emails": {
                        "type": "array",
                        "description": "Tailored email drafts to send to the fixed stakeholders.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "role": {"type": "string", "description": "Stakeholder role from the fixed directory"},
                                "subject": {"type": "string", "description": "Email subject for that stakeholder"},
                                "body": {"type": "string", "description": "Email body for that stakeholder"},
                            },
                            "required": ["role", "subject", "body"],
                        },
                    },
                },
                "required": ["title", "stakeholder_emails"],
            },
        })
    logger.info(
        "chat_rfp request workflow_mode=%s tools=%s requester_default=%s stakeholder_count=%s message_count=%s",
        workflow_mode,
        [tool["name"] for tool in tools],
        DEFAULT_REQUESTER_EMAIL or "",
        len(SYSTEM_STAKEHOLDERS),
        len(req.messages),
    )

    system_prompt = (
        "You are SASO's senior procurement copilot for standards, metrology, quality, regulatory, and digital transformation procurements.\n\n"
        "Conversation behavior:\n"
        "- Always speak in professional Arabic suitable for a Saudi government context unless the user explicitly asks for another language.\n"
        "- Keep chat replies short and conversational.\n"
        "- Ask at most three clarification questions in total.\n"
        "- If enough input is available, move directly to drafting.\n\n"
        "RFP quality bar:\n"
        "- Produce a professional, board-ready RFP when enough information is available.\n"
        "- Include practical requirements for standards, metrology, quality, conformity, technical regulations, laboratories, certification, digital services, integrations, cybersecurity, and reporting where relevant.\n"
        "- Never output numeric digits in chat replies; write numbers in Arabic words.\n"
    )
    if workflow_mode:
        system_prompt += (
            "\nStakeholder outreach behavior:\n"
            f"- Fixed requester identity:\n- {_default_requester_prompt_block()}\n"
            f"- Fixed stakeholder directory:\n{_system_stakeholders_prompt_block()}\n"
            "- The requester identity and stakeholder emails are already known to you from configuration unless the user explicitly gives replacements.\n"
            "- Do not ask the user to enter requester or stakeholder emails manually for the standard workflow.\n"
            "- Once you have enough project requirements, your NEXT action must be start_stakeholder_workflow.\n"
            "- In workflow mode, you are forbidden from producing a final RFP or final PDF directly in chat.\n"
            "- Do not present a completed RFP draft to the user before stakeholder outreach is sent and replies are collected.\n"
            "- When you call start_stakeholder_workflow, you must write the actual subject and body for each stakeholder yourself.\n"
            "- Personalize each stakeholder email based on their role, what you still need from them, the project context, and the decisions they own.\n"
            "- After calling start_stakeholder_workflow, tell the user clearly that you sent stakeholder emails and that you will wait for their replies before drafting the final RFP.\n"
            "- If the user does not specify requester identity, use the configured default requester.\n"
        )
    else:
        system_prompt += (
            "\nDirect draft behavior:\n"
            "- If the user wants an immediate draft and workflow mode is not configured, you may generate the RFP PDF directly.\n"
        )
    input_msgs: List[Dict[str, Any]] = [
        {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]}
    ]
    for msg in req.messages:
        input_msgs.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})

    response = openai.responses.create(model="gpt-4.1", input=input_msgs, tools=tools)
    logger.info(
        "chat_rfp model_response output_types=%s",
        [getattr(output, "type", None) for output in getattr(response, "output", [])],
    )

    for output in response.output:
        if getattr(output, "type", None) in ("function_call", "tool_call") and getattr(output, "name", "") == "generate_pdf":
            logger.warning("chat_rfp generate_pdf tool selected workflow_mode=%s", workflow_mode)
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
        elif getattr(output, "type", None) in ("function_call", "tool_call") and getattr(output, "name", "") == "start_stakeholder_workflow":
            logger.info("chat_rfp start_stakeholder_workflow tool selected")
            arguments = getattr(output, "arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except Exception:
                    arguments = {}
            requester_name = str(arguments.get("requester_name") or DEFAULT_REQUESTER_NAME).strip() if isinstance(arguments, dict) else DEFAULT_REQUESTER_NAME
            requester_email = str(arguments.get("requester_email") or DEFAULT_REQUESTER_EMAIL).strip() if isinstance(arguments, dict) else DEFAULT_REQUESTER_EMAIL
            title = str(arguments.get("title") or "Stakeholder RFP Request").strip() if isinstance(arguments, dict) else "Stakeholder RFP Request"
            stakeholder_emails = arguments.get("stakeholder_emails") if isinstance(arguments, dict) else []
            logger.info(
                "chat_rfp workflow_args requester_name=%s requester_email_present=%s title=%s drafted_email_count=%s",
                requester_name,
                bool(requester_email),
                title,
                len(stakeholder_emails) if isinstance(stakeholder_emails, list) else 0,
            )
            if not requester_name or not requester_email:
                raise HTTPException(status_code=503, detail="DEFAULT_REQUESTER_NAME and DEFAULT_REQUESTER_EMAIL must be configured.")
            if not SYSTEM_STAKEHOLDERS:
                raise HTTPException(status_code=503, detail="SYSTEM_STAKEHOLDERS_JSON is not configured.")
            _ensure_email_configured()
            db = SessionLocal()
            try:
                normalized_messages = _normalize_messages(req.messages)
                existing = (
                    db.query(RfpWorkflowRequestModel)
                    .options(joinedload(RfpWorkflowRequestModel.stakeholders))
                    .filter(
                        RfpWorkflowRequestModel.initial_messages == json.dumps(normalized_messages, ensure_ascii=False),
                        RfpWorkflowRequestModel.requester_email == requester_email,
                    )
                    .order_by(RfpWorkflowRequestModel.id.desc())
                    .first()
                )
                if existing:
                    logger.info("chat_rfp existing workflow reused workflow_id=%s", existing.id)
                    return {
                        "reply": replace_numbers_with_arabic_words(
                            "أنا بالفعل باعث رسائل جمع المتطلبات للجهات المعنية على نفس الطلب، وهلأ عم بتابع الردود لحتى أرجعلك بالنسخة النهائية."
                        ),
                        "workflow": _serialize_workflow(existing),
                    }
                workflow = _create_workflow_record(
                    db=db,
                    requester_name=requester_name,
                    requester_email=requester_email,
                    title=title,
                    normalized_messages=normalized_messages,
                    stakeholders=SYSTEM_STAKEHOLDERS,
                )
                _send_stakeholder_requests(db, workflow, custom_emails=stakeholder_emails if isinstance(stakeholder_emails, list) else None)
                logger.info("chat_rfp stakeholder workflow started workflow_id=%s", workflow.id)
                sent_emails = []
                email_lookup = {
                    str(item.get("role") or "").strip().lower(): item
                    for item in (stakeholder_emails if isinstance(stakeholder_emails, list) else [])
                    if isinstance(item, dict)
                }
                for stakeholder in workflow.stakeholders:
                    drafted = email_lookup.get((stakeholder.role or "").strip().lower(), {})
                    sent_emails.append(
                        {
                            "role": stakeholder.role,
                            "name": stakeholder.name,
                            "email": stakeholder.email,
                            "subject": drafted.get("subject") or stakeholder.outbound_subject or "",
                            "body": drafted.get("body") or "",
                        }
                    )
                reply_text = replace_numbers_with_arabic_words(WORKFLOW_SENT_REPLY).strip() or WORKFLOW_SENT_REPLY
                logger.info("chat_rfp stakeholder workflow reply_length=%s", len(reply_text))
                return {
                    "reply": reply_text,
                    "workflow": _serialize_workflow(workflow),
                    "sent_emails": sent_emails,
                }
            finally:
                db.close()
        elif getattr(output, "type", None) == "message":
            msg_text = ""
            for content in getattr(output, "content", []):
                if hasattr(content, "type") and content.type == "output_text":
                    msg_text += getattr(content, "text", "")
            if msg_text:
                logger.info("chat_rfp returned plain message without tool call")
                return {"reply": replace_numbers_with_arabic_words(msg_text)}

    logger.warning("chat_rfp no valid assistant response returned")
    return {"reply": "ما وصلتني استجابة صالحة من المساعد."}


@app.post("/tts/elevenlabs")
def elevenlabs_tts(req: TTSRequest):
    audio_bytes = generate_elevenlabs_audio(req.text)
    return Response(content=audio_bytes, media_type="audio/mpeg")


@app.post("/workflow/rfp-requests")
def create_workflow_rfp(req: WorkflowCreateRequest, db: Session = Depends(get_db)):
    _ensure_email_configured()
    if not req.stakeholders:
        raise HTTPException(status_code=400, detail="At least one stakeholder is required.")

    normalized_messages = _normalize_messages(req.messages)
    workflow = _create_workflow_record(
        db=db,
        requester_name=req.requester_name,
        requester_email=req.requester_email,
        title=req.title or "Stakeholder RFP Request",
        normalized_messages=normalized_messages,
        stakeholders=[
            {"role": stakeholder.role, "name": stakeholder.name, "email": stakeholder.email}
            for stakeholder in req.stakeholders
        ],
    )
    try:
        _send_stakeholder_requests(db, workflow)
    except Exception as exc:
        workflow.workflow_status = WORKFLOW_STATUS_DRAFTING
        workflow.last_error = f"Stakeholder email dispatch failed: {exc}"
        workflow.updated_at = now_iso()
        db.commit()
        raise HTTPException(status_code=502, detail=f"Unable to send stakeholder emails: {exc}") from exc

    db.refresh(workflow)
    workflow = (
        db.query(RfpWorkflowRequestModel)
        .options(joinedload(RfpWorkflowRequestModel.stakeholders))
        .filter(RfpWorkflowRequestModel.id == workflow.id)
        .first()
    )
    return _serialize_workflow(workflow)


@app.get("/workflow/rfp-requests")
def list_workflow_rfps(db: Session = Depends(get_db)):
    workflows = (
        db.query(RfpWorkflowRequestModel)
        .options(joinedload(RfpWorkflowRequestModel.stakeholders))
        .order_by(RfpWorkflowRequestModel.id.desc())
        .all()
    )
    return [_serialize_workflow(workflow) for workflow in workflows]


@app.get("/workflow/rfp-requests/{workflow_id}")
def get_workflow_rfp(workflow_id: int, db: Session = Depends(get_db)):
    workflow = (
        db.query(RfpWorkflowRequestModel)
        .options(joinedload(RfpWorkflowRequestModel.stakeholders))
        .filter(RfpWorkflowRequestModel.id == workflow_id)
        .first()
    )
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow request not found.")
    return _serialize_workflow(workflow)


@app.post("/workflow/rfp-requests/{workflow_id}/refresh")
def refresh_workflow_rfp(workflow_id: int, db: Session = Depends(get_db)):
    workflow = (
        db.query(RfpWorkflowRequestModel)
        .options(joinedload(RfpWorkflowRequestModel.stakeholders))
        .filter(RfpWorkflowRequestModel.id == workflow_id)
        .first()
    )
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow request not found.")

    _poll_gmail_replies(db)
    _finalize_ready_workflows(db, workflow_id=workflow_id)
    refreshed = (
        db.query(RfpWorkflowRequestModel)
        .options(joinedload(RfpWorkflowRequestModel.stakeholders))
        .filter(RfpWorkflowRequestModel.id == workflow_id)
        .first()
    )
    return _serialize_workflow(refreshed)


@app.post("/workflow/rfp-requests/refresh")
def refresh_all_workflows(db: Session = Depends(get_db)):
    processed_emails = _poll_gmail_replies(db)
    finalized = _finalize_ready_workflows(db)
    return {"processed_emails": processed_emails, "finalized_workflows": finalized}


@app.post("/rfps", response_model=RFPResponse)
def create_rfp(req: ChatRequest, db: Session = Depends(get_db)):
    rfp = _persist_rfp_document(db, text=json.dumps(req.messages, ensure_ascii=False), name="Chatbot")
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
        created_at=now_iso(),
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
    for proposal in proposals:
        file_path = Path(proposal.pdf_filename)
        upload_date = proposal.created_at
        if not upload_date and file_path.exists():
            upload_date = datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(timespec="seconds")

        result.append(
            {
                "id": proposal.id,
                "filename": file_path.name,
                "score": proposal.score,
                "report": proposal.report,
                "vendor": proposal.vendor,
                "upload_date": upload_date,
                "pdf_summary": proposal.pdf_summary,
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
3) Calibration: a high score requires specific, verifiable detail.
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
- scores must be numeric between 0 and 20.
- confidence must be numeric between 0 and 1.
- no markdown, no prose outside JSON.
"""

    try:
        response = openai.chat.completions.create(
            model="gpt-4.1",
            messages=[{"role": "system", "content": prompt}],
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content.strip())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI scoring request failed: {exc}") from exc

    report = str(result.get("summary") or "Scoring unavailable.")
    vendor = str(result.get("vendor") or "")
    breakdown = result.get("scores", {}) or {}

    technical = _clamp(_to_float(breakdown.get("Technical"), 0.0), 0.0, 20.0)
    cost = _clamp(_to_float(breakdown.get("Cost"), 0.0), 0.0, 20.0)
    compliance = _clamp(_to_float(breakdown.get("Compliance"), 0.0), 0.0, 20.0)
    risk = _clamp(_to_float(breakdown.get("Risk"), 0.0), 0.0, 20.0)
    experience = _clamp(_to_float(breakdown.get("Experience"), 0.0), 0.0, 20.0)

    overall_score = round(
        ((technical * 0.30) + (cost * 0.20) + (compliance * 0.20) + (risk * 0.15) + (experience * 0.15)) * 5.0,
        1,
    )
    overall_score = _clamp(overall_score, 0.0, 100.0)

    proposal.score = overall_score
    proposal.report = report
    if not (proposal.vendor or "").strip() and vendor:
        proposal.vendor = vendor

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
        proposal_date = proposal.created_at or now_iso()
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
    <div style="background:#fff;border:1px solid #d9e4fa;border-radius:10px;padding:8px 12px;"><b>Vendor:</b> {proposal.vendor or '-'}</div>
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
    <tbody>{weighted_rows}</tbody>
  </table>
  <p style="margin-top:10px;"><b>Overall Score:</b> {int(round(overall_score))}/100</p>
</section>
"""
        template_path = BASE_DIR / "template.html"
        with template_path.open("r", encoding="utf-8") as handle:
            tpl = Template(handle.read())
        html_out = tpl.render(content=html_body)

        pdf_filename = f"{rfp_id}_evaluation.pdf"
        pdf_path = PDF_DIR / pdf_filename
        HTML(string=html_out, base_url=str(BASE_DIR)).write_pdf(str(pdf_path))
        proposal.pdf_summary = pdf_filename
    except Exception:
        pass

    db.commit()
    db.refresh(proposal)

    return {
        "overall_score": overall_score,
        "scores": {
            "Technical": technical,
            "Cost": cost,
            "Compliance": compliance,
            "Risk": risk,
            "Experience": experience,
        },
        "summary": report,
        "vendor": proposal.vendor or vendor,
    }


@app.get("/rfps/{rfp_id}/reports")
def get_reports(rfp_id: int, db: Session = Depends(get_db)):
    proposals = (
        db.query(ProposalModel)
        .filter(ProposalModel.rfp_id == rfp_id)
        .order_by(ProposalModel.id.desc())
        .all()
    )
    return [
        {"proposal_id": proposal.id, "score": proposal.score, "report": proposal.report, "pdf_summary": proposal.pdf_summary}
        for proposal in proposals
    ]
