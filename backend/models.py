from sqlalchemy import Column, Integer, String, Text, ForeignKey, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

from sqlalchemy import DateTime
from datetime import datetime

class RFP(Base):
    __tablename__ = 'rfps'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    pdf_filename = Column(String, nullable=False)
    status = Column(String, default='Waiting for Proposal')
    score = Column(Float, nullable=True)
    proposals = relationship('Proposal', back_populates='rfp')
    requirements = Column(Text)
    pdf_path = Column(String)


class Proposal(Base):
    __tablename__ = 'proposals'
    id = Column(Integer, primary_key=True, index=True)
    rfp_id = Column(Integer, ForeignKey('rfps.id'), nullable=False)
    pdf_filename = Column(String, nullable=False)
    score = Column(Float, nullable=True)
    vendor = Column(String, nullable=True)
    report = Column(Text, nullable=True)
    pdf_summary = Column(String, nullable=True)  # stores the generated PDF summary filename
    created_at = Column(String, nullable=True)
    rfp = relationship('RFP', back_populates='proposals')
