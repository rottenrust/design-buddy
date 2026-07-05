from aiogram import Bot, Dispatcher

from app.bot.handlers import create_router
from app.services.chat_service import ChatService
from app.services.task_service import TaskService


def create_dispatcher(chat_service: ChatService, task_service: TaskService) -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(create_router(chat_service, task_service))
    return dispatcher


def create_bot(token: str) -> Bot:
    return Bot(token=token)

