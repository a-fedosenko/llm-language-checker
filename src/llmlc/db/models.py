"""Persistence schema.

Two tables carry the project's long-term value: `generation` (the raw corpus,
never deleted, re-gradable when the method changes) and `result` (the publishable
row). Everything else exists to make a scan resumable and a re-run avoidable.

A result is only meaningful together with the configuration that produced it --
back-translator, judge, method version — so those are columns, not metadata, and
they are part of the uniqueness constraint.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (JSON, DateTime, Float, ForeignKey, Index, Integer, String,
                        Text, UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Job(Base):
    """One scan. Resumable: items carry their own state, so a killed job restarts
    from where it stopped rather than from zero."""

    __tablename__ = "job"

    id: Mapped[int] = mapped_column(primary_key=True)
    engine: Mapped[str] = mapped_column(String(128), index=True)
    scheme: Mapped[str] = mapped_column(String(64), default="default")
    pivot: Mapped[str] = mapped_column(String(16), default="en")
    judge: Mapped[str] = mapped_column(String(128))
    backtranslator_panel: Mapped[list] = mapped_column(JSON, default=list)
    method_version: Mapped[str] = mapped_column(String(32), index=True)
    hardware_profile: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    requested_tags: Mapped[list] = mapped_column(JSON, default=list)
    unknown_tags: Mapped[list] = mapped_column(JSON, default=list)
    max_calls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calls_used: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list["JobItem"]] = relationship(back_populates="job",
                                                  cascade="all, delete-orphan")


class JobItem(Base):
    """One equivalence class within a job. The unit of resumption."""

    __tablename__ = "job_item"
    __table_args__ = (UniqueConstraint("job_id", "cls", name="uq_job_item_class"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), index=True)
    cls: Mapped[str] = mapped_column(String(64))
    representative: Mapped[str] = mapped_column(String(64))
    members: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped[Job] = relationship(back_populates="items")


class Result(Base):
    """The publishable row.

    Unique on (engine, tag, method_version, backtranslator): the same language
    measured with a different instrument is a different result, not an update,
    because results from different back-translators are not comparable.
    """

    __tablename__ = "result"
    __table_args__ = (
        UniqueConstraint("engine", "tag", "method_version", "backtranslator",
                         name="uq_result_identity"),
        Index("ix_result_engine_tier", "engine", "tier"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("job.id", ondelete="SET NULL"),
                                               nullable=True, index=True)
    engine: Mapped[str] = mapped_column(String(128), index=True)
    tag: Mapped[str] = mapped_column(String(64), index=True)
    cls: Mapped[str] = mapped_column(String(64), index=True)

    tier: Mapped[str] = mapped_column(String(16))
    evidence: Mapped[str] = mapped_column(String(32), index=True)
    s_lang: Mapped[float] = mapped_column(Float, default=0.0)
    s_content: Mapped[float] = mapped_column(Float, default=0.0)
    ci_low: Mapped[float] = mapped_column(Float, default=0.0)
    ci_high: Mapped[float] = mapped_column(Float, default=0.0)
    borderline: Mapped[bool] = mapped_column(default=False)
    reliability: Mapped[float] = mapped_column(Float, default=1.0)
    refusals: Mapped[int] = mapped_column(Integer, default=0)

    designator: Mapped[str] = mapped_column(String(256))
    designator_detail: Mapped[dict] = mapped_column(JSON, default=dict)
    provenance: Mapped[str] = mapped_column(String(32), default="measured")
    variant_evidence: Mapped[str | None] = mapped_column(String(32), nullable=True)
    inherited_from: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolves_to: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    backtranslator: Mapped[str] = mapped_column(String(128))
    backtranslator_qualification: Mapped[dict] = mapped_column(JSON, default=dict)
    judge: Mapped[str] = mapped_column(String(128))
    pivot: Mapped[str] = mapped_column(String(16), default="en")
    hardware_profile: Mapped[str | None] = mapped_column(String(32), nullable=True)
    method_version: Mapped[str] = mapped_column(String(32), index=True)
    tool_version: Mapped[str | None] = mapped_column(String(32), nullable=True)

    rungs_run: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calls: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    items: Mapped[list | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    tested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                default=utcnow, index=True)


class Generation(Base):
    """The raw corpus. Never deleted: when the method changes this is re-graded
    offline instead of re-running every model."""

    __tablename__ = "generation"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("job.id", ondelete="SET NULL"),
                                               nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)
    engine: Mapped[str] = mapped_column(String(128), index=True)
    tag: Mapped[str] = mapped_column(String(64), index=True)
    spec_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    designator: Mapped[str | None] = mapped_column(String(256), nullable=True)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    latency_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Qualification(Base):
    """Cached per (back-translator, language). Changes only when the
    back-translator does, so it is paid once rather than per run."""

    __tablename__ = "qualification"
    __table_args__ = (UniqueConstraint("backtranslator", "tag", "method_version",
                                       name="uq_qualification_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    backtranslator: Mapped[str] = mapped_column(String(128), index=True)
    tag: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16))
    score: Mapped[float] = mapped_column(Float, default=0.0)
    kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    method_version: Mapped[str] = mapped_column(String(32))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
