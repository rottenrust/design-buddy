from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.prompt_builder import PromptBuilder
from app.agent.schemas import AssistantResult
from app.db.database import create_engine, create_session_factory, init_db
from app.services.chat_service import ChatService
from app.services.task_service import TaskService


class FakeAgentRunner:
    def __init__(self, result: AssistantResult | Exception | None = None) -> None:
        self.result = result or AssistantResult(reply="Ответ", rolling_summary="Кратко")
        self.prompts: list[str] = []

    async def run(self, prompt: str) -> AssistantResult:
        self.prompts.append(prompt)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    await init_db(engine)
    yield create_session_factory(engine)
    await engine.dispose()


@pytest.fixture
def task_service() -> TaskService:
    return TaskService(Path("data/tasks.yaml"))


@pytest.fixture
def prompt_builder() -> PromptBuilder:
    return PromptBuilder(Path("app/prompts/system.md"))


def make_chat_service(
    session_factory: async_sessionmaker[AsyncSession],
    task_service: TaskService,
    prompt_builder: PromptBuilder,
    runner: FakeAgentRunner,
    allowed_user_id: int = 100,
) -> ChatService:
    return ChatService(
        session_factory=session_factory,
        allowed_telegram_user_id=allowed_user_id,
        task_service=task_service,
        prompt_builder=prompt_builder,
        agent_runner=runner,
    )

