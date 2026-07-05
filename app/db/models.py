from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    state: Mapped["UserState"] = relationship(back_populates="user", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[Literal["user", "assistant"]] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class MemoryItem(Base):
    __tablename__ = "memory_items"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_memory_user_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    key: Mapped[str] = mapped_column(String(120))
    value: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class UserState(Base):
    __tablename__ = "user_state"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    active_task_id: Mapped[str | None] = mapped_column(String(120))
    rolling_summary: Mapped[str] = mapped_column(Text, default="")
    onboarding_status: Mapped[Literal["not_started", "in_progress", "completed"]] = mapped_column(
        String(20), default="not_started", server_default="not_started"
    )
    onboarding_skill_id: Mapped[str | None] = mapped_column(String(120))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="state")


class TaskProgress(Base):
    __tablename__ = "task_progress"
    __table_args__ = (UniqueConstraint("user_id", "task_id", name="uq_task_progress_user_task"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    task_id: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[Literal["not_started", "in_progress", "done"]] = mapped_column(
        String(20), default="not_started"
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    review_summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    skill_evidence: Mapped[str] = mapped_column(Text, default="", server_default="")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class SkillAssessment(Base):
    __tablename__ = "skill_assessments"
    __table_args__ = (UniqueConstraint("user_id", "skill_id", name="uq_skill_assessment_user_skill"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    skill_id: Mapped[str] = mapped_column(String(120), index=True)
    self_level: Mapped[str | None] = mapped_column(String(20))
    assessed_level: Mapped[str] = mapped_column(String(20), default="unknown", server_default="unknown")
    confidence: Mapped[str] = mapped_column(String(20), default="low", server_default="low")
    evidence: Mapped[str] = mapped_column(Text, default="", server_default="")
    strengths: Mapped[str] = mapped_column(Text, default="", server_default="")
    gaps: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
