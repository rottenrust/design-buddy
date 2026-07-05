from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.services.task_service import Task


def tasks_keyboard(tasks: list[Task]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=task.title, callback_data=f"task:{task.id}")]
            for task in tasks
        ]
    )


def active_task_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Продолжить задание", callback_data="task_continue")],
            [InlineKeyboardButton(text="Объяснить подробнее", callback_data="task_explain")],
            [InlineKeyboardButton(text="Мой профиль навыков", callback_data="skill_profile")],
            [InlineKeyboardButton(text="Завершить задание", callback_data="task_done")],
            [InlineKeyboardButton(text="Выбрать другое", callback_data="task_choose")],
        ]
    )
