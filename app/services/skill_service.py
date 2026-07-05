from app.agent.schemas import SkillAssessmentUpdate
from app.db.repositories import Repository
from app.services.task_service import TaskService


class SkillService:
    def __init__(self, repository: Repository, task_service: TaskService) -> None:
        self.repository = repository
        self.task_service = task_service

    async def ensure_default_profile(self, user_id: int) -> None:
        for skill in self.task_service.list_skills():
            await self.repository.ensure_skill_assessment(user_id, skill.id)

    async def apply_updates(self, user_id: int, updates: list[SkillAssessmentUpdate]) -> None:
        known_skill_ids = self.task_service.known_skill_ids()
        for update in updates:
            if update.skill_id not in known_skill_ids:
                continue
            assessed_level = update.assessed_level if update.evidence.strip() else None
            await self.repository.upsert_skill_assessment(
                user_id=user_id,
                skill_id=update.skill_id,
                self_level=update.self_level,
                assessed_level=assessed_level,
                confidence=update.confidence,
                evidence=update.evidence,
                strengths=update.strengths,
                gaps=update.gaps,
            )

    async def has_complete_profile(self, user_id: int) -> bool:
        known_skill_ids = self.task_service.known_skill_ids()
        assessments = await self.repository.list_skill_assessments(user_id)
        return known_skill_ids <= {assessment.skill_id for assessment in assessments}
