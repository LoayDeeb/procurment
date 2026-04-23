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
from html import escape
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
from sqlalchemy.exc import IntegrityError

try:
    from .database import SessionLocal, ensure_db_schema, init_db
    from .models import (
        ProcurementConfig as ProcurementConfigModel,
        Proposal as ProposalModel,
        RFP as RFPModel,
        RfpWorkflowRequest as RfpWorkflowRequestModel,
        StakeholderRequest as StakeholderRequestModel,
    )
except ImportError:
    from database import SessionLocal, ensure_db_schema, init_db
    from models import (
        ProcurementConfig as ProcurementConfigModel,
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
WORKFLOW_STATUS_DELIVERING = "delivering"
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


def _normalize_stakeholders(items: Any) -> List[Dict[str, str]]:
    stakeholders: List[Dict[str, str]] = []
    if not isinstance(items, list):
        return stakeholders
    for item in items:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        name = str(item.get("name") or role or "").strip()
        email = str(item.get("email") or "").strip()
        if role and email:
            stakeholders.append({"role": role, "name": name or role, "email": email})
    return stakeholders


def _load_persisted_procurement_config(db: Optional[Session] = None) -> Optional[ProcurementConfigModel]:
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    try:
        return db.query(ProcurementConfigModel).order_by(ProcurementConfigModel.id.asc()).first()
    finally:
        if close_db:
            db.close()


def _get_effective_workflow_config(db: Optional[Session] = None) -> Dict[str, Any]:
    config = _load_persisted_procurement_config(db)
    requester_name = DEFAULT_REQUESTER_NAME
    requester_email = DEFAULT_REQUESTER_EMAIL
    stakeholders = list(SYSTEM_STAKEHOLDERS)
    if config:
        requester_name = (config.requester_name or requester_name or "Procurement Officer").strip()
        requester_email = str(config.requester_email or requester_email or "").strip()
        if config.stakeholders_json:
            try:
                stakeholders = _normalize_stakeholders(json.loads(config.stakeholders_json))
            except Exception:
                stakeholders = []
    return {
        "requester_name": requester_name or "Procurement Officer",
        "requester_email": requester_email,
        "stakeholders": stakeholders,
    }


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def get_db():
    ensure_db_schema()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.on_event("startup")
def on_startup():
    global _workflow_thread_started
    init_db()
    effective_config = _get_effective_workflow_config()
    logger.info(
        "startup config workflow_ready=%s requester_email=%s stakeholder_count=%s gmail_configured=%s public_backend_url=%s",
        _workflow_mode_enabled(),
        bool(effective_config["requester_email"]),
        len(effective_config["stakeholders"]),
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


class ProcurementConfigUpdateRequest(BaseModel):
    requester_name: str = Field(..., min_length=1)
    requester_email: EmailStr
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
    config = _get_effective_workflow_config()
    return bool(
        config["requester_email"]
        and config["stakeholders"]
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


def _generate_evaluation_pdf_file(markdown_text: str, proposal_id: int) -> str:
    filename = f"proposal_{proposal_id}_evaluation.pdf"
    filepath = PDF_DIR / filename
    template_path = BASE_DIR / "template.html"
    try:
        from render_pdf import generate_pdf

        generate_pdf(markdown_text, str(template_path), str(filepath))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate evaluation PDF: {exc}") from exc
    return filename


def _render_evaluation_pdf_html(html_body: str, proposal_id: int) -> str:
    filename = f"proposal_{proposal_id}_evaluation.pdf"
    filepath = PDF_DIR / filename
    template_path = BASE_DIR / "template.html"
    try:
        from jinja2 import Template
        from weasyprint import HTML

        with template_path.open("r", encoding="utf-8") as handle:
            tpl = Template(handle.read())
        html_out = tpl.render(content=html_body)
        HTML(string=html_out, base_url=str(BASE_DIR)).write_pdf(str(filepath))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to render evaluation PDF: {exc}") from exc
    return filename


def _build_evaluation_markdown(
    proposal: ProposalModel,
    rfp_name: str,
    overall_score: Optional[float] = None,
    scores: Optional[Dict[str, float]] = None,
) -> str:
    lines = [
        "# Proposal Evaluation Report",
        "",
        f"**RFP:** {rfp_name or f'RFP {proposal.rfp_id}'}",
        f"**Vendor:** {proposal.vendor or '-'}",
        f"**Uploaded:** {proposal.created_at or '-'}",
        f"**Overall Score:** {('-' if overall_score is None else f'{overall_score:.1f}/100')}",
        "",
        "## Executive Summary",
        proposal.report or "No evaluation summary available.",
    ]
    if scores:
        lines.extend(
            [
                "",
                "## Score Breakdown",
            ]
        )
        for name, value in scores.items():
            lines.append(f"- {name}: {value:.1f}/20")
    return "\n".join(lines)


def _load_evaluation_payload(proposal: ProposalModel) -> Dict[str, Any]:
    raw = proposal.evaluation_payload or ""
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _build_evaluation_html_body(
    proposal: ProposalModel,
    rfp_name: str,
    overall_score: Optional[float] = None,
    scores: Optional[Dict[str, float]] = None,
) -> str:
    payload = _load_evaluation_payload(proposal)
    summary = str(payload.get("summary") or proposal.report or "No evaluation summary available.")
    score_map = scores or payload.get("scores") or {}
    normalized_scores = {
        "Technical": _clamp(_to_float(score_map.get("Technical"), 0.0), 0.0, 20.0),
        "Cost": _clamp(_to_float(score_map.get("Cost"), 0.0), 0.0, 20.0),
        "Compliance": _clamp(_to_float(score_map.get("Compliance"), 0.0), 0.0, 20.0),
        "Risk": _clamp(_to_float(score_map.get("Risk"), 0.0), 0.0, 20.0),
        "Experience": _clamp(_to_float(score_map.get("Experience"), 0.0), 0.0, 20.0),
    }
    effective_overall = overall_score if overall_score is not None else _to_float(proposal.score, 0.0)
    strengths = payload.get("strengths") if isinstance(payload.get("strengths"), list) else []
    risks = payload.get("risks") if isinstance(payload.get("risks"), list) else []
    missing_requirements = payload.get("missing_requirements") if isinstance(payload.get("missing_requirements"), list) else []
    confidence = _clamp(_to_float(payload.get("confidence"), 0.0), 0.0, 1.0)

    chart_b64 = None
    try:
        from score_chart import render_score_dashboard_base64

        if any(value > 0 for value in normalized_scores.values()):
            chart_b64 = render_score_dashboard_base64(normalized_scores, effective_overall)
    except Exception:
        chart_b64 = None

    weighted_rows = "".join(
        f"<tr><td>{name}</td><td>{val:.1f}/20</td><td>{int(round((float(val)/20)*100))}%</td></tr>"
        for name, val in normalized_scores.items()
    )
    decision_tag = "Strong Candidate" if effective_overall >= 80 else "Conditional Review" if effective_overall >= 60 else "High Risk"

    def _render_list(title: str, items: List[str], empty_text: str) -> str:
        if not items:
            return (
                f'<section style="border:1px solid #dbe4f6;border-radius:12px;padding:14px 16px;margin-bottom:12px;">'
                f'<h3 style="margin:0 0 8px 0;color:#1f3280;">{title}</h3>'
                f'<p style="margin:0;color:#5d6b8a;">{empty_text}</p></section>'
            )
        entries = "".join(f"<li style=\"margin-bottom:6px;\">{escape(str(item))}</li>" for item in items)
        return (
            f'<section style="border:1px solid #dbe4f6;border-radius:12px;padding:14px 16px;margin-bottom:12px;">'
            f'<h3 style="margin:0 0 8px 0;color:#1f3280;">{title}</h3>'
            f'<ul style="margin:0;padding-left:18px;color:#33426f;">{entries}</ul></section>'
        )

    chart_section = ""
    if chart_b64:
        chart_section = f"""
<section style="border:1px solid #dbe4f6;border-radius:12px;padding:14px 16px;margin-bottom:12px;">
  <h3 style="margin:0 0 10px 0;color:#1f3280;">Scoring Dashboard</h3>
  <div style="text-align:center;">
    <img src="{chart_b64}" style="width:100%;max-width:860px;border:1px solid #edf2fd;border-radius:12px;" />
  </div>
</section>
"""

    return f"""
<section style="border:1px solid #dbe4f6;border-radius:12px;padding:14px 16px;background:#f8fbff;margin-bottom:12px;">
  <h2 style="margin:0 0 8px 0;color:#1f3280;">Proposal Evaluation Report</h2>
  <div style="display:flex;gap:10px;flex-wrap:wrap;">
    <div style="background:#fff;border:1px solid #d9e4fa;border-radius:10px;padding:8px 12px;"><b>RFP:</b> {escape(rfp_name or f'RFP {proposal.rfp_id}')}</div>
    <div style="background:#fff;border:1px solid #d9e4fa;border-radius:10px;padding:8px 12px;"><b>Vendor:</b> {escape(proposal.vendor or '-')}</div>
    <div style="background:#fff;border:1px solid #d9e4fa;border-radius:10px;padding:8px 12px;"><b>Upload Date:</b> {escape(proposal.created_at or '-')}</div>
    <div style="background:#fff;border:1px solid #d9e4fa;border-radius:10px;padding:8px 12px;"><b>Decision Tag:</b> {decision_tag}</div>
    <div style="background:#fff;border:1px solid #d9e4fa;border-radius:10px;padding:8px 12px;"><b>Confidence:</b> {int(round(confidence * 100))}%</div>
  </div>
</section>

<section style="border:1px solid #dbe4f6;border-radius:12px;padding:14px 16px;margin-bottom:12px;">
  <h3 style="margin:0 0 8px 0;color:#1f3280;">Executive Summary</h3>
  <p style="margin:0;color:#33426f;">{escape(summary)}</p>
</section>

{chart_section}

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
  <p style="margin-top:10px;"><b>Overall Score:</b> {int(round(effective_overall))}/100</p>
</section>

{_render_list("Strengths", strengths, "No strengths were captured in the stored evaluation payload.")}
{_render_list("Key Risks", risks, "No key risks were captured in the stored evaluation payload.")}
{_render_list("Missing Requirements", missing_requirements, "No missing requirements were captured in the stored evaluation payload.")}
"""


def _ensure_proposal_evaluation_pdf(
    db: Session,
    proposal: ProposalModel,
    rfp_name: str,
    overall_score: Optional[float] = None,
    scores: Optional[Dict[str, float]] = None,
) -> str:
    if proposal.pdf_summary:
        existing_path = PDF_DIR / proposal.pdf_summary
        if existing_path.exists():
            return proposal.pdf_summary

    payload = _load_evaluation_payload(proposal)
    if payload:
        html_body = _build_evaluation_html_body(
            proposal=proposal,
            rfp_name=rfp_name,
            overall_score=overall_score if overall_score is not None else proposal.score,
            scores=scores,
        )
        pdf_filename = _render_evaluation_pdf_html(html_body, proposal.id)
    else:
        markdown_text = _build_evaluation_markdown(
            proposal=proposal,
            rfp_name=rfp_name,
            overall_score=overall_score if overall_score is not None else proposal.score,
            scores=scores,
        )
        pdf_filename = _generate_evaluation_pdf_file(markdown_text, proposal.id)
    proposal.pdf_summary = pdf_filename
    db.commit()
    db.refresh(proposal)
    return pdf_filename


def _persist_rfp_document(
    db: Session,
    text: str,
    name: str,
    source_workflow_id: Optional[int] = None,
) -> RFPModel:
    if source_workflow_id is not None:
        existing = (
            db.query(RFPModel)
            .filter(RFPModel.source_workflow_id == source_workflow_id)
            .first()
        )
        if existing:
            return existing

    filename = _generate_rfp_pdf_file(text)
    rfp = RFPModel(
        name=name,
        pdf_filename=filename,
        source_workflow_id=source_workflow_id,
        requirements=text,
        pdf_path=f"/pdfs/{filename}",
    )
    db.add(rfp)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if source_workflow_id is not None:
            existing = (
                db.query(RFPModel)
                .filter(RFPModel.source_workflow_id == source_workflow_id)
                .first()
            )
            if existing:
                return existing
        raise
    db.refresh(rfp)
    return rfp


def generate_rfp_pdf(text: str) -> str:
    db = SessionLocal()
    try:
        rfp = _persist_rfp_document(db, text=text, name="Chatbot")
        return rfp.pdf_filename
    finally:
        db.close()


def _render_html_list(items: List[str], ordered: bool = False, escape_items: bool = True) -> str:
    tag = "ol" if ordered else "ul"
    item_html = "".join(
        f'<li style="margin: 0 0 8px 0;">{escape(item) if escape_items else item}</li>'
        for item in items
        if str(item).strip()
    )
    if not item_html:
        return ""
    return (
        f'<{tag} style="margin: 0; padding-left: 20px; color: #33426f; font-size: 14px; '
        f'line-height: 22px;">{item_html}</{tag}>'
    )


def _text_to_email_html(text: str) -> str:
    def _format_inline_markup(value: str) -> str:
        escaped = escape(value)
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        escaped = re.sub(r"\*(.+?)\*", r"<em>\1</em>", escaped)
        return escaped

    cleaned = (text or "").replace("\r\n", "\n").strip()
    if not cleaned:
        return (
            '<p style="margin: 0; color: #33426f; font-size: 14px; line-height: 22px;">'
            "No additional details were provided."
            "</p>"
        )

    blocks = re.split(r"\n\s*\n", cleaned)
    html_blocks: List[str] = []

    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue

        if all(re.match("^(?:[-*]|\\u2022)\\s+", line) for line in lines):
            items = [re.sub("^(?:[-*]|\\u2022)\\s+", "", line).strip() for line in lines]
            html_blocks.append(
                _render_html_list([_format_inline_markup(item) for item in items], escape_items=False)
            )
            continue

        if all(re.match(r"^\d+[.)]\s+", line) for line in lines):
            items = [re.sub(r"^\d+[.)]\s+", "", line).strip() for line in lines]
            html_blocks.append(
                _render_html_list([_format_inline_markup(item) for item in items], ordered=True, escape_items=False)
            )
            continue

        paragraph = "<br />".join(_format_inline_markup(line) for line in lines)
        html_blocks.append(
            '<p style="margin: 0 0 14px 0; color: #33426f; font-size: 14px; line-height: 22px;">'
            f"{paragraph}"
            "</p>"
        )

    return "".join(html_blocks) or (
        '<p style="margin: 0; color: #33426f; font-size: 14px; line-height: 22px;">'
        "No additional details were provided."
        "</p>"
    )


def _build_email_section(title: str, body_html: str) -> str:
    return (
        '<div style="margin: 0 0 18px 0; padding: 22px 24px; background: #ffffff; '
        'border: 1px solid #d9e3f5; border-radius: 20px; box-shadow: 0 10px 24px rgba(39, 62, 145, 0.06);">'
        f'<p style="margin: 0 0 14px 0; color: #60709c; font-size: 11px; font-weight: 700; '
        f'letter-spacing: 0.08em; text-transform: uppercase;">{escape(title)}</p>'
        f"{body_html}"
        "</div>"
    )


def _build_highlight_band(label: str, value: str, tone: str = "blue") -> str:
    tones = {
        "blue": {
            "bg": "#eef4ff",
            "border": "#cbdafb",
            "label": "#60709c",
            "value": "#22367f",
        },
        "gold": {
            "bg": "#fff7ea",
            "border": "#efd29a",
            "label": "#8f6a23",
            "value": "#6f4f14",
        },
    }
    palette = tones.get(tone, tones["blue"])
    return (
        f'<div style="display: inline-block; min-width: 180px; margin: 0 10px 10px 0; padding: 12px 14px; '
        f'background: {palette["bg"]}; border: 1px solid {palette["border"]}; border-radius: 14px;">'
        f'<p style="margin: 0 0 6px 0; color: {palette["label"]}; font-size: 10px; font-weight: 700; '
        f'letter-spacing: 0.08em; text-transform: uppercase;">{escape(label)}</p>'
        f'<p style="margin: 0; color: {palette["value"]}; font-size: 15px; line-height: 20px; font-weight: 700;">{escape(value)}</p>'
        "</div>"
    )


def _build_reply_instruction_panel(title: str, steps: List[str], note: str = "") -> str:
    note_html = ""
    if note:
        note_html = (
            f'<p style="margin: 14px 0 0 0; color: #5f6b85; font-size: 12px; line-height: 19px;">{escape(note)}</p>'
        )
    return (
        '<div style="margin: 0 0 18px 0; padding: 24px; background: linear-gradient(180deg, #243a88 0%, #1f2e69 100%); '
        'border-radius: 22px; color: #ffffff;">'
        f'<p style="margin: 0 0 14px 0; color: rgba(255,255,255,0.72); font-size: 11px; font-weight: 700; '
        f'letter-spacing: 0.08em; text-transform: uppercase;">{escape(title)}</p>'
        '<p style="margin: 0 0 14px 0; font-size: 22px; line-height: 28px; font-weight: 700;">Reply to this email thread</p>'
        f'{_render_html_list(steps, ordered=True).replace("#33426f", "rgba(255,255,255,0.92)")}'
        f"{note_html}"
        "</div>"
    )


def _build_email_shell(
    *,
    preheader: str,
    heading: str,
    subtitle: str,
    badge: str = "",
    intro_html: str = "",
    sections_html: List[str],
    footer_html: str,
) -> str:
    badge_html = ""
    if badge:
        badge_html = (
            '<div style="margin: 0 0 16px 0;">'
            '<span style="display: inline-block; padding: 7px 13px; border-radius: 999px; '
            'background: rgba(255, 255, 255, 0.14); border: 1px solid rgba(255,255,255,0.22); color: #ffffff; font-size: 11px; '
            f'font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;">{escape(badge)}</span>'
            "</div>"
        )

    subtitle_html = ""
    if subtitle:
        subtitle_html = (
            f'<p style="margin: 12px 0 0 0; color: rgba(255, 255, 255, 0.82); '
            f'font-size: 14px; line-height: 22px;">{escape(subtitle)}</p>'
        )

    return (
        "<!doctype html>"
        '<html lang="en">'
        '<body style="margin: 0; padding: 0; background: #edf2fd; font-family: Arial, Helvetica, sans-serif;">'
        f'<div style="display: none; max-height: 0; overflow: hidden; opacity: 0; color: transparent;">{escape(preheader)}</div>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="width: 100%; background: #edf2fd; margin: 0; padding: 0;">'
        '<tr><td align="center" style="padding: 28px 14px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="max-width: 700px; width: 100%; background: #ffffff; border: 1px solid #d6dff1; '
        'border-radius: 32px; overflow: hidden; box-shadow: 0 18px 40px rgba(34, 54, 127, 0.12);">'
        '<tr><td style="padding: 0;">'
        '<div style="padding: 36px 38px 34px 38px; background-color: #1f3178; '
        'background: radial-gradient(circle at top right, rgba(255,255,255,0.16), transparent 36%), '
        'linear-gradient(135deg, #243a88 0%, #1a2758 100%); '
        'color: #ffffff;">'
        '<p style="margin: 0 0 16px 0; color: rgba(255,255,255,0.62); font-size: 12px; line-height: 18px; letter-spacing: 0.08em; text-transform: uppercase;">Procurement Copilot</p>'
        f"{badge_html}"
        f'<h1 style="margin: 0; font-size: 32px; line-height: 38px; font-weight: 700;">{escape(heading)}</h1>'
        f"{subtitle_html}"
        "</div>"
        "</td></tr>"
        '<tr><td style="padding: 30px 38px 10px 38px;">'
        f"{intro_html}"
        "</td></tr>"
        '<tr><td style="padding: 0 38px 12px 38px;">'
        f'{"".join(sections_html)}'
        "</td></tr>"
        '<tr><td style="padding: 8px 38px 38px 38px;">'
        f"{footer_html}"
        "</td></tr>"
        "</table>"
        "</td></tr>"
        "</table>"
        "</body>"
        "</html>"
    )


def _build_tracking_footer(token: str, requester_name: str, requester_email: str) -> str:
    requester_line = requester_name.strip() or "Procurement Copilot"
    if requester_email:
        requester_line = f"{requester_line} ({requester_email})"
    return (
        '<div style="padding: 20px 22px; background: #fbfcff; border: 1px solid #dbe4f3; border-radius: 20px;">'
        '<p style="margin: 0 0 6px 0; color: #60709c; font-size: 11px; font-weight: 700; '
        'letter-spacing: 0.08em; text-transform: uppercase;">Tracking Token</p>'
        f'<p style="margin: 0 0 10px 0; color: #22367f; font-size: 16px; font-weight: 700;">{escape(token)}</p>'
        '<p style="margin: 0; color: #5f6b85; font-size: 13px; line-height: 20px;">'
        "Keep this token in the email subject so the workflow can match your reply automatically."
        "</p>"
        "</div>"
        f'<p style="margin: 16px 0 0 0; color: #6a7898; font-size: 12px; line-height: 19px;">'
        f"Sent by Procurement Copilot on behalf of {escape(requester_line)}."
        "</p>"
    )


def _build_stakeholder_email_html(
    workflow: RfpWorkflowRequestModel,
    stakeholder: StakeholderRequestModel,
    token: str,
    body: str,
    custom_body: bool = False,
) -> str:
    summary_text = workflow.initial_summary or "No summary available."
    top_bands = (
        _build_highlight_band("Workflow", workflow.title, tone="blue")
        + _build_highlight_band("Your Role", stakeholder.role, tone="gold")
    )
    intro_html = (
        f'<p style="margin: 0 0 14px 0; color: #22367f; font-size: 20px; line-height: 28px; font-weight: 700;">'
        f"Hello {escape(stakeholder.name)},"
        "</p>"
        f'<div style="margin: 0 0 18px 0;">{top_bands}</div>'
    )

    if custom_body:
        intro_html += (
            '<p style="margin: 0; color: #33426f; font-size: 15px; line-height: 24px;">'
            f'Your input is needed for <strong>{escape(workflow.title)}</strong>.'
            "</p>"
        )
        sections = [
            _build_email_section("Message", _text_to_email_html(body)),
            _build_reply_instruction_panel(
                "Response Method",
                [
                    "Reply directly to this same email thread.",
                    "Include requirements, constraints, approvals, risks, dependencies, and mandatory conditions.",
                    "Keep the tracking token in the subject line.",
                ],
                note="No portal form is needed. Your email reply is the response channel.",
            ),
        ]
    else:
        sections = [
            _build_email_section(
                "Request Summary",
                _text_to_email_html(summary_text),
            ),
            _build_email_section(
                "What To Send",
                _render_html_list(
                    [
                        "Business and functional requirements you own.",
                        "Constraints, approvals, dependencies, and delivery assumptions.",
                        "Operational, compliance, security, or legal risks.",
                        "Any mandatory conditions that must appear in the final RFP.",
                    ]
                ),
            ),
            _build_reply_instruction_panel(
                "Response Method",
                [
                    "Reply directly to this email thread.",
                    "Add your requirements and any mandatory conditions.",
                    "Keep the subject unchanged so the workflow can match your response automatically.",
                ],
                note="No external form or upload step is required unless you choose to attach supporting files.",
            ),
        ]
        intro_html += (
            '<p style="margin: 0; color: #33426f; font-size: 15px; line-height: 24px;">'
            f"{escape(workflow.requester_name)} has started a procurement RFP workflow and needs your input as "
            f"<strong>{escape(stakeholder.role)}</strong>."
            "</p>"
        )

    return _build_email_shell(
        preheader=f"Input needed from {stakeholder.role} for {workflow.title}",
        heading="Stakeholder Input Needed",
        subtitle=workflow.title,
        badge=stakeholder.role,
        intro_html=intro_html,
        sections_html=sections,
        footer_html=_build_tracking_footer(token, workflow.requester_name, workflow.requester_email),
    )


def _build_requester_delivery_email_html(workflow: RfpWorkflowRequestModel, download_url: str) -> str:
    top_bands = (
        _build_highlight_band("Workflow", workflow.title, tone="blue")
        + _build_highlight_band("Workflow ID", str(workflow.id), tone="gold")
    )
    intro_html = (
        f'<p style="margin: 0 0 14px 0; color: #22367f; font-size: 20px; line-height: 28px; font-weight: 700;">'
        f"Hello {escape(workflow.requester_name)},"
        "</p>"
        f'<div style="margin: 0 0 18px 0;">{top_bands}</div>'
        '<p style="margin: 0; color: #33426f; font-size: 15px; line-height: 24px;">'
        "Your stakeholder requirements have been collected and the final RFP draft is ready."
        "</p>"
    )
    button_html = (
        f'<a href="{escape(download_url, quote=True)}" '
        'style="display: inline-block; padding: 14px 20px; border-radius: 14px; background: #243a88; '
        'color: #ffffff; font-size: 14px; font-weight: 700; text-decoration: none; box-shadow: 0 10px 22px rgba(36, 58, 136, 0.28);">'
        "Download Final RFP PDF"
        "</a>"
    )
    sections = [
        _build_email_section(
            "Ready For Review",
            (
                '<p style="margin: 0 0 14px 0; color: #33426f; font-size: 15px; line-height: 24px;">'
                "Use the link below to open the final PDF."
                "</p>"
                f'<p style="margin: 0 0 14px 0;">{button_html}</p>'
                f'<p style="margin: 0; color: #5f6b85; font-size: 12px; line-height: 19px;">'
                f"{escape(download_url)}"
                "</p>"
            ),
        ),
        _build_email_section(
            "Workflow Details",
            _render_html_list(
                [
                    f"Workflow ID: {workflow.id}",
                    f"Title: {workflow.title}",
                    "A copy is also available in the procurement application.",
                ]
            ),
        ),
    ]
    footer_html = (
        '<div style="padding: 18px 20px; background: #f7f9fe; border: 1px solid #dbe4f3; border-radius: 20px;">'
        '<p style="margin: 0; color: #6a7898; font-size: 12px; line-height: 19px;">'
        "Generated by Procurement Copilot after stakeholder responses were merged into the final draft."
        "</p>"
        "</div>"
    )
    return _build_email_shell(
        preheader=f"Final RFP ready for {workflow.title}",
        heading="Final RFP Ready",
        subtitle=workflow.title,
        badge="Delivery",
        intro_html=intro_html,
        sections_html=sections,
        footer_html=footer_html,
    )


def _send_email(
    to_address: str,
    subject: str,
    body: str,
    html_body: Optional[str] = None,
    extra_headers: Optional[Dict[str, str]] = None,
) -> str:
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
    if html_body:
        message.add_alternative(html_body, subtype="html")

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
    return {
        "subject": subject,
        "body": body,
        "html_body": _build_stakeholder_email_html(
            workflow=workflow,
            stakeholder=stakeholder,
            token=token,
            body=body,
        ),
    }


def _send_stakeholder_requests(
    db: Session,
    workflow: RfpWorkflowRequestModel,
    custom_emails: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, str]]:
    custom_by_role = {}
    dispatched_emails: List[Dict[str, str]] = []
    for item in custom_emails or []:
        role = str(item.get("role") or "").strip().lower()
        if role:
            custom_by_role[role] = item
    for stakeholder in workflow.stakeholders:
        if stakeholder.status == STAKEHOLDER_STATUS_RECEIVED:
            continue
        custom_email = custom_by_role.get((stakeholder.role or "").strip().lower())
        email_content = (
            {
                "subject": str(custom_email.get("subject") or "").strip(),
                "body": str(custom_email.get("body") or "").strip(),
                "html_body": str(custom_email.get("html_body") or "").strip(),
            }
            if custom_email
            else _build_stakeholder_email(workflow, stakeholder)
        )
        if not email_content["subject"] or not email_content["body"]:
            email_content = _build_stakeholder_email(workflow, stakeholder)
        elif not email_content.get("html_body"):
            token = f"[RFP-REQ-{workflow.id}-{stakeholder.id}]"
            email_content["html_body"] = _build_stakeholder_email_html(
                workflow=workflow,
                stakeholder=stakeholder,
                token=token,
                body=email_content["body"],
                custom_body=True,
            )
        outbound_message_id = _send_email(
            to_address=stakeholder.email,
            subject=email_content["subject"],
            body=email_content["body"],
            html_body=email_content.get("html_body") or None,
        )
        stakeholder.outbound_subject = email_content["subject"]
        stakeholder.outbound_message_id = outbound_message_id
        stakeholder.status = STAKEHOLDER_STATUS_REQUESTED
        stakeholder.updated_at = now_iso()
        dispatched_emails.append(
            {
                "role": stakeholder.role,
                "name": stakeholder.name,
                "email": stakeholder.email,
                "subject": email_content["subject"],
                "body": email_content["body"],
                "html_body": email_content.get("html_body") or "",
            }
        )
    workflow.workflow_status = WORKFLOW_STATUS_AWAITING
    workflow.updated_at = now_iso()
    workflow.last_error = None
    db.commit()
    return dispatched_emails


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
    return {
        "subject": subject,
        "body": body,
        "html_body": _build_requester_delivery_email_html(workflow, download_url),
    }


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


def _serialize_procurement_config(config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "requester_name": config["requester_name"],
        "requester_email": config["requester_email"],
        "stakeholders": config["stakeholders"],
        "workflow_ready": bool(
            config["requester_email"]
            and config["stakeholders"]
            and GMAIL_ADDRESS
            and GMAIL_APP_PASSWORD
        ),
        "gmail_configured": bool(GMAIL_ADDRESS and GMAIL_APP_PASSWORD),
    }


def _system_stakeholders_prompt_block() -> str:
    stakeholders = _get_effective_workflow_config()["stakeholders"]
    if not stakeholders:
        return "No stakeholder directory is configured."
    lines = []
    for item in stakeholders:
        lines.append(f'- {item["role"]}: {item["name"]} <{item["email"]}>')
    return "\n".join(lines)


def _default_requester_prompt_block() -> str:
    config = _get_effective_workflow_config()
    if config["requester_email"]:
        return f'{config["requester_name"]} <{config["requester_email"]}>'
    return f'{config["requester_name"]} <not configured>'


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
    if workflow.workflow_status == WORKFLOW_STATUS_DELIVERED or workflow.delivered_at:
        return

    claimed_at = now_iso()
    claimed = (
        db.query(RfpWorkflowRequestModel)
        .filter(
            RfpWorkflowRequestModel.id == workflow.id,
            RfpWorkflowRequestModel.workflow_status == WORKFLOW_STATUS_FINAL_READY,
            RfpWorkflowRequestModel.delivered_at.is_(None),
        )
        .update(
            {
                RfpWorkflowRequestModel.workflow_status: WORKFLOW_STATUS_DELIVERING,
                RfpWorkflowRequestModel.updated_at: claimed_at,
                RfpWorkflowRequestModel.last_error: None,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    if not claimed:
        return

    delivery_workflow = (
        db.query(RfpWorkflowRequestModel)
        .filter(RfpWorkflowRequestModel.id == workflow.id)
        .first()
    )
    if not delivery_workflow or not delivery_workflow.final_pdf_filename:
        return

    email_content = _build_requester_delivery_email(delivery_workflow)
    try:
        _send_email(
            to_address=delivery_workflow.requester_email,
            subject=email_content["subject"],
            body=email_content["body"],
            html_body=email_content.get("html_body") or None,
        )
    except Exception as exc:
        delivery_workflow.workflow_status = WORKFLOW_STATUS_FINAL_READY
        delivery_workflow.updated_at = now_iso()
        delivery_workflow.last_error = f"Requester email delivery failed: {exc}"
        db.commit()
        raise

    delivery_workflow.workflow_status = WORKFLOW_STATUS_DELIVERED
    delivery_workflow.delivered_at = now_iso()
    delivery_workflow.updated_at = now_iso()
    delivery_workflow.last_error = None
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
                rfp = _persist_rfp_document(
                    db,
                    text=final_text,
                    name=workflow.title,
                    source_workflow_id=workflow.id,
                )
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
    workflow_config = _get_effective_workflow_config()
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
        workflow_config["requester_email"] or "",
        len(workflow_config["stakeholders"]),
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
            requester_name = str(arguments.get("requester_name") or workflow_config["requester_name"]).strip() if isinstance(arguments, dict) else workflow_config["requester_name"]
            requester_email = str(arguments.get("requester_email") or workflow_config["requester_email"]).strip() if isinstance(arguments, dict) else workflow_config["requester_email"]
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
                raise HTTPException(status_code=503, detail="Requester name and requester email must be configured.")
            if not workflow_config["stakeholders"]:
                raise HTTPException(status_code=503, detail="At least one stakeholder must be configured.")
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
                    stakeholders=workflow_config["stakeholders"],
                )
                sent_emails = _send_stakeholder_requests(
                    db,
                    workflow,
                    custom_emails=stakeholder_emails if isinstance(stakeholder_emails, list) else None,
                )
                logger.info("chat_rfp stakeholder workflow started workflow_id=%s", workflow.id)
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


@app.get("/workflow/config")
def get_workflow_config(db: Session = Depends(get_db)):
    return _serialize_procurement_config(_get_effective_workflow_config(db))


@app.put("/workflow/config")
def update_workflow_config(req: ProcurementConfigUpdateRequest, db: Session = Depends(get_db)):
    config = db.query(ProcurementConfigModel).order_by(ProcurementConfigModel.id.asc()).first()
    timestamp = now_iso()
    stakeholders = [
        {"role": stakeholder.role, "name": stakeholder.name, "email": str(stakeholder.email)}
        for stakeholder in req.stakeholders
    ]
    if not stakeholders:
        raise HTTPException(status_code=400, detail="At least one stakeholder is required.")

    if not config:
        config = ProcurementConfigModel(created_at=timestamp, updated_at=timestamp)
        db.add(config)

    config.requester_name = req.requester_name.strip()
    config.requester_email = str(req.requester_email).strip()
    config.stakeholders_json = json.dumps(stakeholders, ensure_ascii=False)
    config.updated_at = timestamp
    db.commit()
    return _serialize_procurement_config(_get_effective_workflow_config(db))


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


@app.get("/proposals/{proposal_id}/evaluation-pdf")
def download_proposal_evaluation_pdf(proposal_id: int, db: Session = Depends(get_db)):
    proposal = (
        db.query(ProposalModel, RFPModel)
        .join(RFPModel, ProposalModel.rfp_id == RFPModel.id)
        .filter(ProposalModel.id == proposal_id)
        .first()
    )
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    proposal_record, rfp = proposal
    if proposal_record.score is None and not (proposal_record.report or "").strip():
        raise HTTPException(status_code=409, detail="Evaluation report is not ready for this proposal.")

    filename = _ensure_proposal_evaluation_pdf(
        db=db,
        proposal=proposal_record,
        rfp_name=rfp.name or f"RFP {proposal_record.rfp_id}",
    )
    filepath = PDF_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Evaluation PDF not found")
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

    score_breakdown = {
        "Technical": technical,
        "Cost": cost,
        "Compliance": compliance,
        "Risk": risk,
        "Experience": experience,
    }
    proposal.evaluation_payload = json.dumps(
        {
            "vendor": vendor or proposal.vendor or "",
            "summary": report,
            "scores": score_breakdown,
            "strengths": result.get("strengths") if isinstance(result.get("strengths"), list) else [],
            "risks": result.get("risks") if isinstance(result.get("risks"), list) else [],
            "missing_requirements": result.get("missing_requirements") if isinstance(result.get("missing_requirements"), list) else [],
            "confidence": _clamp(_to_float(result.get("confidence"), 0.0), 0.0, 1.0),
        },
        ensure_ascii=False,
    )

    try:
        html_body = _build_evaluation_html_body(
            proposal=proposal,
            rfp_name=rfp.name or f"RFP #{rfp_id}",
            overall_score=overall_score,
            scores=score_breakdown,
        )
        pdf_filename = _render_evaluation_pdf_html(html_body, proposal.id)
        proposal.pdf_summary = pdf_filename
    except Exception:
        logger.exception("proposal evaluation pdf generation via weasyprint failed proposal_id=%s", proposal.id)

    if not proposal.pdf_summary:
        try:
            _ensure_proposal_evaluation_pdf(
                db=db,
                proposal=proposal,
                rfp_name=rfp.name or f"RFP #{rfp_id}",
                overall_score=overall_score,
                scores=score_breakdown,
            )
        except Exception:
            logger.exception("proposal evaluation pdf fallback generation failed proposal_id=%s", proposal.id)

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
