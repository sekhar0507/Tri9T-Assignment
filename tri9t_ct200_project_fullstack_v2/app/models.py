from sqlalchemy import String, Integer, Text, ForeignKey, Boolean, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, timezone
from .database import Base

def utcnow():
    return datetime.now(timezone.utc)

class DocumentVersion(Base):
    __tablename__ = "document_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_key: Mapped[str] = mapped_column(String(120), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    source_filename: Mapped[str] = mapped_column(String(255))
    source_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    nodes: Mapped[list["SectionNode"]] = relationship(back_populates="version", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("document_key", "version_number", name="uq_doc_version"),)

class SectionNode(Base):
    __tablename__ = "section_nodes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id"), index=True)
    logical_key: Mapped[str] = mapped_column(String(500), index=True)
    heading: Mapped[str] = mapped_column(Text)
    section_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    level: Mapped[int] = mapped_column(Integer)
    body_text: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("section_nodes.id"), nullable=True)
    parent: Mapped["SectionNode | None"] = relationship(remote_side="SectionNode.id", back_populates="children")
    children: Mapped[list["SectionNode"]] = relationship(back_populates="parent", cascade="save-update")
    version: Mapped["DocumentVersion"] = relationship(back_populates="nodes")
    __table_args__ = (UniqueConstraint("version_id", "logical_key", name="uq_version_logical_key"),)

class SavedSelection(Base):
    __tablename__ = "selections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    document_key: Mapped[str] = mapped_column(String(120), index=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    items: Mapped[list["SelectionItem"]] = relationship(back_populates="selection", cascade="all, delete-orphan")

class SelectionItem(Base):
    __tablename__ = "selection_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    selection_id: Mapped[int] = mapped_column(ForeignKey("selections.id"), index=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("section_nodes.id"))
    version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id"))
    logical_key_snapshot: Mapped[str] = mapped_column(String(500))
    heading_snapshot: Mapped[str] = mapped_column(Text)
    body_snapshot: Mapped[str] = mapped_column(Text)
    content_hash_snapshot: Mapped[str] = mapped_column(String(64))
    selection: Mapped["SavedSelection"] = relationship(back_populates="items")

class GenerationRecord(Base):
    __tablename__ = "generation_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    selection_id: Mapped[int] = mapped_column(ForeignKey("selections.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    provider: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40))
    source_hashes_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text)
    validation_warnings_json: Mapped[str] = mapped_column(Text, default="[]")
