from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, JSON, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pipeline_id = Column(String(64), unique=True, nullable=False, index=True)
    topic = Column(String(255), nullable=False)
    status = Column(String(32), default="running")
    completed_agents = Column(JSON, default=list)
    errors = Column(JSON, default=list)
    output_dir = Column(Text)
    video_path = Column(Text)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)


class Script(Base):
    __tablename__ = "scripts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pipeline_id = Column(String(64), nullable=False, index=True)
    topic = Column(String(255))
    sections = Column(JSON)
    full_text = Column(Text)
    word_count = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
