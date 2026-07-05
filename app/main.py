import asyncio
import logging
from pathlib import Path

from app.agent.prompt_builder import PromptBuilder
from app.agent.runner import AgentRunner
from app.bot.setup import create_bot, create_dispatcher
from app.config import get_settings
from app.db.database import create_engine, create_session_factory, init_db
from app.services.chat_service import ChatService
from app.services.task_service import TaskService


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    engine = create_engine(settings.database_url)
    await init_db(engine)
    session_factory = create_session_factory(engine)

    task_service = TaskService(Path("data/tasks.yaml"))
    prompt_builder = PromptBuilder(Path("app/prompts/system.md"))
    chat_service = ChatService(
        session_factory=session_factory,
        allowed_telegram_user_id=settings.allowed_telegram_user_id,
        task_service=task_service,
        prompt_builder=prompt_builder,
        agent_runner=AgentRunner(),
    )

    bot = create_bot(settings.telegram_bot_token)
    dispatcher = create_dispatcher(chat_service, task_service)
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

