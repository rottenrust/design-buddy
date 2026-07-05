from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.prompt_builder import AgentContext, PromptBuilder
from app.agent.runner import AgentRunError, AgentRunner
from app.agent.schemas import AssistantResult
from app.db.repositories import Repository
from app.services.memory_service import MemoryService
from app.services.skill_service import SkillService
from app.services.task_service import TaskService


FALLBACK_REPLY = (
    "Сейчас я не смог подготовить ответ. Твоё сообщение сохранено — попробуй написать ещё раз "
    "немного позже."
)
FORBIDDEN_REPLY = "Этот бот доступен только владельцу."


@dataclass(frozen=True)
class ChatResponse:
    reply: str
    allowed: bool = True


class ChatService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        allowed_telegram_user_id: int,
        task_service: TaskService,
        prompt_builder: PromptBuilder,
        agent_runner: AgentRunner,
    ) -> None:
        self.session_factory = session_factory
        self.allowed_telegram_user_id = allowed_telegram_user_id
        self.task_service = task_service
        self.prompt_builder = prompt_builder
        self.agent_runner = agent_runner

    async def start(self, telegram_user_id: int, display_name: str | None) -> ChatResponse:
        if not self._is_allowed(telegram_user_id):
            return ChatResponse(FORBIDDEN_REPLY, allowed=False)

        async with self.session_factory() as session:
            repository = Repository(session)
            user = await repository.get_or_create_user(telegram_user_id, display_name)
            state = await repository.ensure_user_state(user.id)
            await SkillService(repository, self.task_service).ensure_default_profile(user.id)
            if state.onboarding_status != "completed":
                await repository.set_onboarding_state(
                    user.id,
                    "in_progress",
                    state.onboarding_skill_id or self._first_skill_id(),
                )
            await session.commit()
            onboarding_status = state.onboarding_status

        if onboarding_status != "completed":
            return await self._run_agent_turn(
                telegram_user_id,
                display_name,
                "Начни или продолжи первичный опрос. Задай один главный вопрос.",
            )
        return ChatResponse(await self._home_message(telegram_user_id, display_name))

    async def process_user_message(
        self, telegram_user_id: int, display_name: str | None, text: str
    ) -> ChatResponse:
        return await self._run_agent_turn(telegram_user_id, display_name, text)

    async def continue_active_task(
        self, telegram_user_id: int, display_name: str | None
    ) -> ChatResponse:
        return await self._run_agent_turn(
            telegram_user_id,
            display_name,
            "Продолжи активное задание: дай текущий или следующий маленький шаг.",
        )

    async def explain_active_task(
        self, telegram_user_id: int, display_name: str | None
    ) -> ChatResponse:
        return await self._run_agent_turn(
            telegram_user_id,
            display_name,
            "Объясни текущий шаг активного задания проще, с коротким примером и микро-шагом.",
        )

    async def tasks_overview(self, telegram_user_id: int, display_name: str | None) -> ChatResponse:
        if not self._is_allowed(telegram_user_id):
            return ChatResponse(FORBIDDEN_REPLY, allowed=False)
        async with self.session_factory() as session:
            repository = Repository(session)
            user = await repository.get_or_create_user(telegram_user_id, display_name)
            progress_items = await repository.list_task_progress(user.id)
        by_task = {item.task_id: item.status for item in progress_items}
        lines = ["Карта навыков и заданий:"]
        for task in self.task_service.list_tasks():
            skill = self.task_service.get_skill(task.skill_id)
            status = by_task.get(task.id, "not_started")
            skill_title = skill.title if skill else task.skill_id
            lines.append(f"- {skill_title}: {task.title} — {status}")
        return ChatResponse("\n".join(lines))

    async def profile_summary(self, telegram_user_id: int, display_name: str | None) -> ChatResponse:
        if not self._is_allowed(telegram_user_id):
            return ChatResponse(FORBIDDEN_REPLY, allowed=False)
        async with self.session_factory() as session:
            repository = Repository(session)
            user = await repository.get_or_create_user(telegram_user_id, display_name)
            await SkillService(repository, self.task_service).ensure_default_profile(user.id)
            assessments = await repository.list_skill_assessments(user.id)
            await session.commit()
        by_skill = {assessment.skill_id: assessment for assessment in assessments}
        lines = ["Профиль навыков:"]
        for skill in self.task_service.list_skills():
            assessment = by_skill.get(skill.id)
            if assessment is None:
                lines.append(f"- {skill.title}: данных пока нет")
                continue
            evidence = assessment.evidence or "evidence пока нет"
            lines.append(
                f"- {skill.title}: self={assessment.self_level or 'unknown'}, "
                f"assessed={assessment.assessed_level}, confidence={assessment.confidence}. "
                f"Основание: {evidence}"
            )
        return ChatResponse("\n".join(lines))

    async def select_task(
        self, telegram_user_id: int, display_name: str | None, task_id: str
    ) -> ChatResponse:
        if not self._is_allowed(telegram_user_id):
            return ChatResponse(FORBIDDEN_REPLY, allowed=False)
        task = self.task_service.get_task(task_id)
        if task is None:
            return ChatResponse("Не нашёл такое задание.")
        async with self.session_factory() as session:
            repository = Repository(session)
            user = await repository.get_or_create_user(telegram_user_id, display_name)
            await repository.set_active_task(user.id, task.id)
            await session.commit()
        actor = display_name or "Пользователь"
        return await self._run_agent_turn(
            telegram_user_id,
            display_name,
            f"{actor} выбрал(а) задание {task.title}. Начни учебный сценарий: назови навык, "
            "ожидаемый результат и дай первый маленький шаг.",
        )

    async def complete_active_task(
        self, telegram_user_id: int, display_name: str | None
    ) -> ChatResponse:
        if not self._is_allowed(telegram_user_id):
            return ChatResponse(FORBIDDEN_REPLY, allowed=False)
        async with self.session_factory() as session:
            repository = Repository(session)
            user = await repository.get_or_create_user(telegram_user_id, display_name)
            state = await repository.ensure_user_state(user.id)
            if not state.active_task_id:
                return ChatResponse("Сейчас нет активного задания.")
            task = self.task_service.get_task(state.active_task_id)
            progress = await repository.get_task_progress(user.id, state.active_task_id)
            await repository.mark_task_done(user.id, state.active_task_id)
            if task and progress and progress.skill_evidence:
                await repository.upsert_skill_assessment(
                    user_id=user.id,
                    skill_id=task.skill_id,
                    self_level=None,
                    assessed_level="guided",
                    confidence="medium",
                    evidence=progress.skill_evidence,
                    strengths=[],
                    gaps=[],
                )
            await session.commit()
        return ChatResponse("Готово, отметила задание завершённым.")

    async def _run_agent_turn(
        self, telegram_user_id: int, display_name: str | None, text: str
    ) -> ChatResponse:
        if not self._is_allowed(telegram_user_id):
            return ChatResponse(FORBIDDEN_REPLY, allowed=False)

        async with self.session_factory() as session:
            repository = Repository(session)
            user = await repository.get_or_create_user(telegram_user_id, display_name)
            await SkillService(repository, self.task_service).ensure_default_profile(user.id)
            user_message = await repository.add_message(user.id, "user", text)
            await session.commit()

            state = await repository.ensure_user_state(user.id)
            active_task = self.task_service.get_task(state.active_task_id)
            active_progress = (
                await repository.get_task_progress(user.id, active_task.id) if active_task else None
            )
            context = AgentContext(
                memory=await repository.list_memory(user.id, limit=20),
                skills=self.task_service.list_skills(),
                skill_assessments=await repository.list_skill_assessments(user.id),
                state=state,
                active_task=active_task,
                active_task_progress=active_progress,
                recent_messages=await repository.list_recent_messages(
                    user.id, limit=12, before_message_id=user_message.id
                ),
                user_message=text,
            )
            prompt = self.prompt_builder.build(context)

        try:
            result = await self.agent_runner.run(prompt)
            self._validate_agent_result(result)
        except AgentRunError:
            return ChatResponse(FALLBACK_REPLY)

        async with self.session_factory() as session:
            repository = Repository(session)
            user = await repository.get_or_create_user(telegram_user_id, display_name)
            state = await repository.ensure_user_state(user.id)
            skill_service = SkillService(repository, self.task_service)
            await repository.add_message(user.id, "assistant", result.reply)
            await repository.set_rolling_summary(user.id, result.rolling_summary[:1500])
            await MemoryService(repository).apply_updates(user.id, result.memory_updates)
            await skill_service.apply_updates(user.id, result.skill_updates)
            if state.active_task_id and result.task_note:
                await repository.append_task_note(user.id, state.active_task_id, result.task_note)
                await repository.set_task_review(
                    user.id,
                    state.active_task_id,
                    review_summary=result.task_note,
                    skill_evidence=result.task_note if result.task_completion_suggested else None,
                )
            if state.onboarding_status != "completed":
                if result.onboarding_completion_suggested and await skill_service.has_complete_profile(
                    user.id
                ):
                    await repository.set_onboarding_state(user.id, "completed", None)
                else:
                    await repository.set_onboarding_state(
                        user.id,
                        "in_progress",
                        await self._next_onboarding_skill_id(repository, user.id),
                    )
            await session.commit()
        return ChatResponse(result.reply)

    async def _home_message(self, telegram_user_id: int, display_name: str | None) -> str:
        async with self.session_factory() as session:
            repository = Repository(session)
            user = await repository.get_or_create_user(telegram_user_id, display_name)
            state = await repository.ensure_user_state(user.id)
        if state.active_task_id:
            task = self.task_service.get_task(state.active_task_id)
            if task:
                return f"Продолжаем. Активное задание: {task.title}."
        task = self._recommended_task(None)
        return f"Привет! Опрос завершён. Рекомендую начать с задания: {task.title}."

    async def _next_onboarding_skill_id(self, repository: Repository, user_id: int) -> str | None:
        assessments = await repository.list_skill_assessments(user_id)
        by_skill = {assessment.skill_id: assessment for assessment in assessments}
        for skill in self.task_service.list_skills():
            assessment = by_skill.get(skill.id)
            if assessment is None or (
                assessment.self_level is None and not (assessment.evidence or "").strip()
            ):
                return skill.id
        return self._first_skill_id()

    def _validate_agent_result(self, result: AssistantResult) -> None:
        known_skill_ids = self.task_service.known_skill_ids()
        unknown_skill_ids = [
            update.skill_id for update in result.skill_updates if update.skill_id not in known_skill_ids
        ]
        if unknown_skill_ids:
            raise AgentRunError(f"Unknown skill_id in agent result: {', '.join(unknown_skill_ids)}")

    def _recommended_task(self, assessments):
        return self.task_service.list_tasks()[0]

    def _first_skill_id(self) -> str | None:
        skills = self.task_service.list_skills()
        return skills[0].id if skills else None

    def _is_allowed(self, telegram_user_id: int) -> bool:
        return telegram_user_id == self.allowed_telegram_user_id
