from app.agent.schemas import MemoryUpdate
from app.db.repositories import Repository


ALLOWED_MEMORY_KEYS = {
    "professional_goal",
    "experience",
    "current_projects",
    "tools",
    "feedback_style",
    "pace",
    "constraints",
    "role",
    "focus",
    "portfolio",
    "preferred_feedback",
    "learning_pace",
}


class MemoryService:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    async def apply_updates(self, user_id: int, updates: list[MemoryUpdate]) -> None:
        for update in updates[:5]:
            if update.key not in ALLOWED_MEMORY_KEYS:
                continue
            await self.repository.upsert_memory(user_id, update.key, update.value)
