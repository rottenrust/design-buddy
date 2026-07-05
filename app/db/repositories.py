from collections.abc import Sequence
import json

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MemoryItem, Message, SkillAssessment, TaskProgress, User, UserState, utcnow


class Repository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create_user(self, telegram_user_id: int, display_name: str | None) -> User:
        user = await self.get_user_by_telegram_id(telegram_user_id)
        if user is None:
            user = User(telegram_user_id=telegram_user_id, display_name=display_name)
            self.session.add(user)
            await self.session.flush()
            self.session.add(UserState(user_id=user.id))
            await self.session.flush()
            return user
        if display_name and user.display_name != display_name:
            user.display_name = display_name
        await self.ensure_user_state(user.id)
        return user

    async def get_user_by_telegram_id(self, telegram_user_id: int) -> User | None:
        result = await self.session.execute(
            select(User).where(User.telegram_user_id == telegram_user_id)
        )
        return result.scalar_one_or_none()

    async def ensure_user_state(self, user_id: int) -> UserState:
        state = await self.get_user_state(user_id)
        if state is None:
            state = UserState(user_id=user_id)
            self.session.add(state)
            await self.session.flush()
        return state

    async def get_user_state(self, user_id: int) -> UserState | None:
        result = await self.session.execute(select(UserState).where(UserState.user_id == user_id))
        return result.scalar_one_or_none()

    async def set_onboarding_state(
        self, user_id: int, status: str, skill_id: str | None = None
    ) -> None:
        state = await self.ensure_user_state(user_id)
        state.onboarding_status = status
        state.onboarding_skill_id = skill_id
        await self.session.flush()

    async def add_message(self, user_id: int, role: str, text: str) -> Message:
        message = Message(user_id=user_id, role=role, text=text)
        self.session.add(message)
        await self.session.flush()
        return message

    async def list_recent_messages(
        self, user_id: int, limit: int, before_message_id: int | None = None
    ) -> list[Message]:
        conditions = [Message.user_id == user_id]
        if before_message_id is not None:
            conditions.append(Message.id < before_message_id)
        statement: Select[tuple[Message]] = (
            select(Message)
            .where(*conditions)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
        result = await self.session.execute(statement)
        return list(reversed(result.scalars().all()))

    async def list_memory(self, user_id: int, limit: int = 20) -> list[MemoryItem]:
        result = await self.session.execute(
            select(MemoryItem)
            .where(MemoryItem.user_id == user_id)
            .order_by(MemoryItem.updated_at.desc(), MemoryItem.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def upsert_memory(self, user_id: int, key: str, value: str) -> MemoryItem:
        result = await self.session.execute(
            select(MemoryItem).where(MemoryItem.user_id == user_id, MemoryItem.key == key)
        )
        item = result.scalar_one_or_none()
        if item is None:
            item = MemoryItem(user_id=user_id, key=key, value=value)
            self.session.add(item)
        else:
            item.value = value
        await self.session.flush()
        return item

    async def set_rolling_summary(self, user_id: int, rolling_summary: str) -> None:
        state = await self.ensure_user_state(user_id)
        state.rolling_summary = rolling_summary
        await self.session.flush()

    async def set_active_task(self, user_id: int, task_id: str) -> TaskProgress:
        state = await self.ensure_user_state(user_id)
        state.active_task_id = task_id
        progress = await self.get_task_progress(user_id, task_id)
        if progress is None:
            progress = TaskProgress(user_id=user_id, task_id=task_id, status="in_progress")
            self.session.add(progress)
        elif progress.status == "not_started":
            progress.status = "in_progress"
        await self.session.flush()
        return progress

    async def get_task_progress(self, user_id: int, task_id: str) -> TaskProgress | None:
        result = await self.session.execute(
            select(TaskProgress).where(
                TaskProgress.user_id == user_id,
                TaskProgress.task_id == task_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_task_progress(self, user_id: int) -> Sequence[TaskProgress]:
        result = await self.session.execute(
            select(TaskProgress).where(TaskProgress.user_id == user_id)
        )
        return result.scalars().all()

    async def append_task_note(self, user_id: int, task_id: str, note: str) -> None:
        progress = await self.get_task_progress(user_id, task_id)
        if progress is None:
            progress = TaskProgress(user_id=user_id, task_id=task_id, status="in_progress")
            self.session.add(progress)
        progress.notes = "\n\n".join(part for part in [progress.notes.strip(), note.strip()] if part)
        progress.attempt_count = (progress.attempt_count or 0) + 1
        await self.session.flush()

    async def set_task_review(
        self, user_id: int, task_id: str, review_summary: str | None, skill_evidence: str | None
    ) -> None:
        progress = await self.get_task_progress(user_id, task_id)
        if progress is None:
            progress = TaskProgress(user_id=user_id, task_id=task_id, status="in_progress")
            self.session.add(progress)
        if review_summary:
            progress.review_summary = review_summary
        if skill_evidence:
            progress.skill_evidence = skill_evidence
        await self.session.flush()

    async def mark_task_done(self, user_id: int, task_id: str) -> None:
        progress = await self.get_task_progress(user_id, task_id)
        if progress is None:
            progress = TaskProgress(user_id=user_id, task_id=task_id, status="done")
            self.session.add(progress)
        else:
            progress.status = "done"
        progress.completed_at = utcnow()
        await self.session.flush()

    async def list_skill_assessments(self, user_id: int) -> list[SkillAssessment]:
        result = await self.session.execute(
            select(SkillAssessment)
            .where(SkillAssessment.user_id == user_id)
            .order_by(SkillAssessment.skill_id)
        )
        return list(result.scalars().all())

    async def get_skill_assessment(
        self, user_id: int, skill_id: str
    ) -> SkillAssessment | None:
        result = await self.session.execute(
            select(SkillAssessment).where(
                SkillAssessment.user_id == user_id,
                SkillAssessment.skill_id == skill_id,
            )
        )
        return result.scalar_one_or_none()

    async def ensure_skill_assessment(
        self,
        user_id: int,
        skill_id: str,
        self_level: str | None = None,
        assessed_level: str = "unknown",
        confidence: str = "low",
        evidence: str = "",
        strengths: list[str] | None = None,
        gaps: list[str] | None = None,
    ) -> SkillAssessment:
        assessment = await self.get_skill_assessment(user_id, skill_id)
        if assessment is None:
            assessment = SkillAssessment(
                user_id=user_id,
                skill_id=skill_id,
                self_level=self_level,
                assessed_level=assessed_level,
                confidence=confidence,
                evidence=evidence,
                strengths=_dump_list(strengths or []),
                gaps=_dump_list(gaps or []),
            )
            self.session.add(assessment)
            await self.session.flush()
        return assessment

    async def upsert_skill_assessment(
        self,
        user_id: int,
        skill_id: str,
        self_level: str | None,
        assessed_level: str | None,
        confidence: str,
        evidence: str,
        strengths: list[str],
        gaps: list[str],
    ) -> SkillAssessment:
        assessment = await self.ensure_skill_assessment(user_id, skill_id)
        if self_level is not None:
            assessment.self_level = self_level
        if assessed_level is not None and evidence.strip():
            assessment.assessed_level = assessed_level
        assessment.confidence = confidence
        if evidence.strip():
            assessment.evidence = evidence.strip()
        if strengths:
            assessment.strengths = _dump_list(strengths)
        if gaps:
            assessment.gaps = _dump_list(gaps)
        await self.session.flush()
        return assessment


def _dump_list(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False)


def load_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return [value]
    if isinstance(data, list):
        return [str(item) for item in data]
    return [str(data)]
