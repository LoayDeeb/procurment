from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class RFP(Base):
    __tablename__ = "rfps"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    pdf_filename = Column(String, nullable=False)
    source_workflow_id = Column(Integer, nullable=True)
    status = Column(String, default="Waiting for Proposal")
    score = Column(Float, nullable=True)
    requirements = Column(Text)
    pdf_path = Column(String)
    proposals = relationship("Proposal", back_populates="rfp")


class Proposal(Base):
    __tablename__ = "proposals"

    id = Column(Integer, primary_key=True, index=True)
    rfp_id = Column(Integer, ForeignKey("rfps.id"), nullable=False)
    pdf_filename = Column(String, nullable=False)
    score = Column(Float, nullable=True)
    vendor = Column(String, nullable=True)
    report = Column(Text, nullable=True)
    evaluation_payload = Column(Text, nullable=True)
    pdf_summary = Column(String, nullable=True)
    created_at = Column(String, nullable=True)
    rfp = relationship("RFP", back_populates="proposals")


class RfpWorkflowRequest(Base):
    __tablename__ = "rfp_workflow_requests"

    id = Column(Integer, primary_key=True, index=True)
    requester_name = Column(String, nullable=False)
    requester_email = Column(String, nullable=False)
    title = Column(String, nullable=False, default="Stakeholder RFP Request")
    active_dedupe_key = Column(String, nullable=True)
    initial_messages = Column(Text, nullable=False)
    initial_summary = Column(Text, nullable=True)
    workflow_status = Column(String, nullable=False, default="drafting")
    final_rfp_text = Column(Text, nullable=True)
    final_pdf_filename = Column(String, nullable=True)
    final_rfp_id = Column(Integer, ForeignKey("rfps.id"), nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    delivered_at = Column(String, nullable=True)

    stakeholders = relationship(
        "StakeholderRequest",
        back_populates="workflow",
        cascade="all, delete-orphan",
    )
    final_rfp = relationship("RFP")


class StakeholderRequest(Base):
    __tablename__ = "stakeholder_requests"

    id = Column(Integer, primary_key=True, index=True)
    workflow_request_id = Column(Integer, ForeignKey("rfp_workflow_requests.id"), nullable=False)
    role = Column(String, nullable=False)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    outbound_subject = Column(String, nullable=True)
    outbound_message_id = Column(String, nullable=True)
    reply_message_id = Column(String, nullable=True)
    reply_excerpt = Column(Text, nullable=True)
    extracted_requirements = Column(Text, nullable=True)
    replied_at = Column(String, nullable=True)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    workflow = relationship("RfpWorkflowRequest", back_populates="stakeholders")


class ProcurementConfig(Base):
    __tablename__ = "procurement_config"

    id = Column(Integer, primary_key=True, index=True)
    requester_name = Column(String, nullable=False, default="Procurement Officer")
    requester_email = Column(String, nullable=True)
    stakeholders_json = Column(Text, nullable=True)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
