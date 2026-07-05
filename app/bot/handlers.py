from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import active_task_keyboard, tasks_keyboard
from app.services.chat_service import ChatService
from app.services.task_service import TaskService


def create_router(chat_service: ChatService, task_service: TaskService) -> Router:
    router = Router()

    @router.message(Command("start"))
    async def start(message: Message) -> None:
        if message.from_user is None:
            return
        response = await chat_service.start(message.from_user.id, message.from_user.full_name)
        await message.answer(response.reply)

    @router.message(Command("tasks"))
    async def tasks(message: Message) -> None:
        if message.from_user is None:
            return
        response = await chat_service.tasks_overview(
            message.from_user.id,
            message.from_user.full_name,
        )
        if not response.allowed:
            await message.answer(response.reply)
            return
        await message.answer(response.reply, reply_markup=tasks_keyboard(task_service.list_tasks()))

    @router.callback_query(lambda query: query.data and query.data.startswith("task:"))
    async def select_task(callback: CallbackQuery) -> None:
        if callback.from_user is None or callback.data is None or callback.message is None:
            return
        task_id = callback.data.removeprefix("task:")
        response = await chat_service.select_task(
            callback.from_user.id,
            callback.from_user.full_name,
            task_id,
        )
        await callback.message.answer(response.reply, reply_markup=active_task_keyboard())
        await callback.answer()

    @router.callback_query(lambda query: query.data == "task_choose")
    async def choose_task(callback: CallbackQuery) -> None:
        if callback.message is None:
            return
        await callback.message.answer(
            "Выбери задание:", reply_markup=tasks_keyboard(task_service.list_tasks())
        )
        await callback.answer()

    @router.callback_query(lambda query: query.data == "task_continue")
    async def continue_task(callback: CallbackQuery) -> None:
        if callback.from_user is None or callback.message is None:
            return
        response = await chat_service.continue_active_task(
            callback.from_user.id,
            callback.from_user.full_name,
        )
        await callback.message.answer(response.reply, reply_markup=active_task_keyboard())
        await callback.answer()

    @router.callback_query(lambda query: query.data == "task_explain")
    async def explain_task(callback: CallbackQuery) -> None:
        if callback.from_user is None or callback.message is None:
            return
        response = await chat_service.explain_active_task(
            callback.from_user.id,
            callback.from_user.full_name,
        )
        await callback.message.answer(response.reply, reply_markup=active_task_keyboard())
        await callback.answer()

    @router.callback_query(lambda query: query.data == "skill_profile")
    async def skill_profile(callback: CallbackQuery) -> None:
        if callback.from_user is None or callback.message is None:
            return
        response = await chat_service.profile_summary(
            callback.from_user.id,
            callback.from_user.full_name,
        )
        await callback.message.answer(response.reply, reply_markup=active_task_keyboard())
        await callback.answer()

    @router.callback_query(lambda query: query.data == "task_done")
    async def complete_task(callback: CallbackQuery) -> None:
        if callback.from_user is None or callback.message is None:
            return
        response = await chat_service.complete_active_task(
            callback.from_user.id,
            callback.from_user.full_name,
        )
        await callback.message.answer(response.reply)
        await callback.answer()

    @router.message()
    async def message_handler(message: Message) -> None:
        if message.from_user is None or message.text is None:
            return
        response = await chat_service.process_user_message(
            message.from_user.id,
            message.from_user.full_name,
            message.text,
        )
        await message.answer(response.reply)

    return router
