from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, text

from app.agent.runner import AgentRunError, AgentRunner, build_strict_output_schema
from app.agent.schemas import AssistantResult, MemoryUpdate, SkillAssessmentUpdate
from app.db.database import create_engine, create_session_factory, init_db
from app.db.models import MemoryItem, Message, SkillAssessment, TaskProgress, User, UserState
from app.db.repositories import Repository
from app.services.chat_service import FALLBACK_REPLY
from app.services.task_service import TaskService
from conftest import FakeAgentRunner, make_chat_service

EXPECTED_SKILLS = [
    "problem_framing",
    "research_planning",
    "user_interviews",
    "research_synthesis",
    "user_needs",
    "user_flows",
    "information_architecture",
    "interaction_design",
    "prototyping",
    "usability_testing",
    "accessibility",
    "design_rationale",
]


def _contains_key(value, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(child, key) for child in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


def test_strict_output_schema_is_codex_compatible():
    schema = build_strict_output_schema()

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "reply",
        "memory_updates",
        "skill_updates",
        "rolling_summary",
        "task_note",
        "task_completion_suggested",
        "onboarding_completion_suggested",
    }
    assert schema["$defs"]["MemoryUpdate"]["additionalProperties"] is False
    assert schema["$defs"]["SkillAssessmentUpdate"]["additionalProperties"] is False
    assert not _contains_key(schema, "default")


def test_agent_runner_passes_model_and_reasoning_without_resume():
    runner = AgentRunner(command=("codex", "exec"))

    command = runner._build_command(Path("schema.json"), Path("result.json"))

    assert command[:2] == ("codex", "exec")
    assert command[command.index("-m") + 1] == "gpt-5.4-mini"
    assert command[command.index("-c") + 1] == 'model_reasoning_effort="medium"'
    assert "--ephemeral" in command
    assert "resume" not in command


def test_task_catalog_contains_all_v02_skills(task_service):
    skills = task_service.list_skills()

    assert [skill.id for skill in skills] == EXPECTED_SKILLS
    assert len(task_service.list_tasks()) == 12


def test_each_skill_has_exactly_one_task(task_service):
    tasks = task_service.list_tasks()

    assert sorted(task.skill_id for task in tasks) == sorted(EXPECTED_SKILLS)
    assert all(task.deliverables for task in tasks)
    assert all(task.rubric for task in tasks)
    assert all(task.learning_steps for task in tasks)


def test_task_with_unknown_skill_id_is_rejected(tmp_path):
    path = tmp_path / "tasks.yaml"
    path.write_text(
        """
skills:
  - id: known
    order: 10
    title: Known
    description: Known skill
    diagnostic_questions:
      - Question?
tasks:
  - id: bad
    skill_id: missing
    order: 10
    title: Bad
    why_it_matters: Why
    context: Context
    brief: Brief
    deliverables:
      - Deliverable
    learning_steps:
      - Step
    explanation_topics:
      - Topic
    rubric:
      - id: one
        title: One
    common_mistakes:
      - Mistake
    done_definition: Done
""",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        TaskService(path).load_catalog()


async def test_start_creates_new_user_and_begins_onboarding(
    session_factory, task_service, prompt_builder
):
    runner = FakeAgentRunner(AssistantResult(reply="Начнём с цели.", rolling_summary="Опрос."))
    service = make_chat_service(session_factory, task_service, prompt_builder, runner)

    response = await service.start(100, "Тестовый пользователь")

    assert response.allowed is True
    assert response.reply == "Начнём с цели."
    assert len(runner.prompts) == 1
    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.telegram_user_id == 100))
        state = await session.get(UserState, user.id)
        assessments = (await session.execute(select(SkillAssessment))).scalars().all()
    assert state.onboarding_status == "in_progress"
    assert state.onboarding_skill_id == "problem_framing"
    assert len(assessments) == 12


async def test_wrong_telegram_id_does_not_run_agent(session_factory, task_service, prompt_builder):
    runner = FakeAgentRunner()
    service = make_chat_service(session_factory, task_service, prompt_builder, runner)

    response = await service.process_user_message(999, "Кто-то", "Привет")

    assert response.allowed is False
    assert runner.prompts == []


async def test_onboarding_state_survives_reinitialization(tmp_path, task_service, prompt_builder):
    db_path = tmp_path / "persist.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    service = make_chat_service(session_factory, task_service, prompt_builder, FakeAgentRunner())
    await service.start(100, "Тестовый пользователь")
    await engine.dispose()

    second_engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    await init_db(second_engine)
    second_factory = create_session_factory(second_engine)
    async with second_factory() as session:
        user = await session.scalar(select(User).where(User.telegram_user_id == 100))
        state = await session.get(UserState, user.id)
    await second_engine.dispose()
    assert state.onboarding_status == "in_progress"


async def test_onboarding_completion_keeps_full_skill_profile(
    session_factory, task_service, prompt_builder
):
    runner = FakeAgentRunner(
        AssistantResult(
            reply="Профиль готов.",
            rolling_summary="Опрос завершён.",
            onboarding_completion_suggested=True,
            skill_updates=[
                SkillAssessmentUpdate(
                    skill_id="problem_framing",
                    self_level="guided",
                    assessed_level="awareness",
                    confidence="medium",
                    evidence="Пользователь объяснил проблему через пользователя и контекст.",
                    strengths=["видит контекст"],
                    gaps=["нужно меньше решений в problem statement"],
                )
            ],
        )
    )
    service = make_chat_service(session_factory, task_service, prompt_builder, runner)

    await service.start(100, "Тестовый пользователь")

    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.telegram_user_id == 100))
        state = await session.get(UserState, user.id)
        assessments = (await session.execute(select(SkillAssessment))).scalars().all()
        framing = await session.scalar(
            select(SkillAssessment).where(SkillAssessment.skill_id == "problem_framing")
        )
    assert state.onboarding_status == "completed"
    assert len(assessments) == 12
    assert framing.assessed_level == "awareness"


async def test_self_assessment_does_not_update_assessed_level_without_evidence(
    session_factory, task_service, prompt_builder
):
    runner = FakeAgentRunner(
        AssistantResult(
            reply="Записала самооценку.",
            rolling_summary="Самооценка.",
            skill_updates=[
                SkillAssessmentUpdate(
                    skill_id="problem_framing",
                    self_level="independent",
                    assessed_level="independent",
                    confidence="high",
                    evidence="",
                )
            ],
        )
    )
    service = make_chat_service(session_factory, task_service, prompt_builder, runner)

    await service.process_user_message(100, "Тестовый пользователь", "Я уверенно формулирую проблемы")

    async with session_factory() as session:
        assessment = await session.scalar(
            select(SkillAssessment).where(SkillAssessment.skill_id == "problem_framing")
        )
    assert assessment.self_level == "independent"
    assert assessment.assessed_level == "unknown"


async def test_unknown_skill_from_agent_result_is_rejected(
    session_factory, task_service, prompt_builder
):
    runner = FakeAgentRunner(
        AssistantResult(
            reply="Ответ",
            rolling_summary="Summary",
            skill_updates=[SkillAssessmentUpdate(skill_id="unknown_skill", confidence="low")],
        )
    )
    service = make_chat_service(session_factory, task_service, prompt_builder, runner)

    response = await service.process_user_message(100, "Тестовый пользователь", "Привет")

    assert response.reply == FALLBACK_REPLY
    async with session_factory() as session:
        assistant_count = await session.scalar(
            select(func.count(Message.id)).where(Message.role == "assistant")
        )
    assert assistant_count == 0


async def test_select_task_sets_active_task(session_factory, task_service, prompt_builder):
    service = make_chat_service(session_factory, task_service, prompt_builder, FakeAgentRunner())

    await service.select_task(100, "Тестовый пользователь", "problem_framing_task")

    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.telegram_user_id == 100))
        state = await session.get(UserState, user.id)
    assert state.active_task_id == "problem_framing_task"


async def test_selecting_new_task_keeps_previous_progress(
    session_factory, task_service, prompt_builder
):
    service = make_chat_service(session_factory, task_service, prompt_builder, FakeAgentRunner())

    await service.select_task(100, "Тестовый пользователь", "problem_framing_task")
    await service.select_task(100, "Тестовый пользователь", "research_planning_task")

    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.telegram_user_id == 100))
        progress = (
            await session.execute(select(TaskProgress).where(TaskProgress.user_id == user.id))
        ).scalars()
    assert {item.task_id for item in progress} == {
        "problem_framing_task",
        "research_planning_task",
    }


async def test_agent_suggestion_does_not_complete_task(
    session_factory, task_service, prompt_builder
):
    runner = FakeAgentRunner(
        AssistantResult(
            reply="Похоже, можно завершать.",
            rolling_summary="Обсудили задание.",
            task_completion_suggested=True,
        )
    )
    service = make_chat_service(session_factory, task_service, prompt_builder, runner)

    await service.select_task(100, "Тестовый пользователь", "problem_framing_task")
    await service.process_user_message(100, "Тестовый пользователь", "Готово?")

    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.telegram_user_id == 100))
        progress = await session.scalar(
            select(TaskProgress).where(
                TaskProgress.user_id == user.id,
                TaskProgress.task_id == "problem_framing_task",
            )
        )
    assert progress.status == "in_progress"


async def test_confirmed_completion_saves_skill_evidence(
    session_factory, task_service, prompt_builder
):
    runner = FakeAgentRunner(
        AssistantResult(
            reply="Критерии выполнены.",
            rolling_summary="Задание.",
            task_note="Пользователь сформулировал пользователя, контекст и последствия проблемы.",
            task_completion_suggested=True,
        )
    )
    service = make_chat_service(session_factory, task_service, prompt_builder, runner)

    await service.select_task(100, "Тестовый пользователь", "problem_framing_task")
    await service.process_user_message(100, "Тестовый пользователь", "Вот мой результат")
    await service.complete_active_task(100, "Тестовый пользователь")

    async with session_factory() as session:
        progress = await session.scalar(
            select(TaskProgress).where(TaskProgress.task_id == "problem_framing_task")
        )
        assessment = await session.scalar(
            select(SkillAssessment).where(SkillAssessment.skill_id == "problem_framing")
        )
    assert progress.status == "done"
    assert progress.completed_at is not None
    assert assessment.assessed_level == "guided"
    assert "пользователя" in assessment.evidence


async def test_memory_upsert_updates_existing_key(session_factory):
    async with session_factory() as session:
        repository = Repository(session)
        user = await repository.get_or_create_user(100, "Тестовый пользователь")
        await repository.upsert_memory(user.id, "role", "junior")
        await repository.upsert_memory(user.id, "role", "middle")
        await session.commit()

    async with session_factory() as session:
        items = (await session.execute(select(MemoryItem))).scalars().all()
    assert len(items) == 1
    assert items[0].value == "middle"


async def test_context_contains_no_more_than_12_messages(
    session_factory, task_service, prompt_builder
):
    runner = FakeAgentRunner()
    service = make_chat_service(session_factory, task_service, prompt_builder, runner)
    async with session_factory() as session:
        repository = Repository(session)
        user = await repository.get_or_create_user(100, "Тестовый пользователь")
        for index in range(15):
            await repository.add_message(user.id, "user", f"old-{index}")
        await session.commit()

    await service.process_user_message(100, "Тестовый пользователь", "new")

    prompt = runner.prompts[0]
    assert "old-0" not in prompt
    assert "old-2" not in prompt
    assert "old-3" in prompt


async def test_prompt_contains_skill_profile_and_active_task_rubric(
    session_factory, task_service, prompt_builder
):
    runner = FakeAgentRunner()
    service = make_chat_service(session_factory, task_service, prompt_builder, runner)

    await service.select_task(100, "Тестовый пользователь", "problem_framing_task")
    await service.process_user_message(100, "Тестовый пользователь", "Продолжим")

    prompt = runner.prompts[-1]
    assert "Профиль навыков:" in prompt
    assert "problem_framing / Формулирование пользовательской проблемы" in prompt
    assert "rubric:" in prompt
    assert "Понятно, о каком пользователе" in prompt
    assert "learning_steps:" in prompt


async def test_invalid_agent_result_does_not_change_memory_profile_or_progress(
    session_factory, task_service, prompt_builder
):
    runner = FakeAgentRunner(AgentRunError("bad json"))
    service = make_chat_service(session_factory, task_service, prompt_builder, runner)

    response = await service.process_user_message(100, "Тестовый пользователь", "Запомни роль")

    assert response.reply == FALLBACK_REPLY
    async with session_factory() as session:
        memory_count = await session.scalar(select(func.count(MemoryItem.id)))
        assistant_count = await session.scalar(
            select(func.count(Message.id)).where(Message.role == "assistant")
        )
        progress_count = await session.scalar(select(func.count(TaskProgress.id)))
    assert memory_count == 0
    assert assistant_count == 0
    assert progress_count == 0


async def test_state_survives_reinitialization(tmp_path, task_service, prompt_builder):
    db_path = tmp_path / "persist.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    service = make_chat_service(session_factory, task_service, prompt_builder, FakeAgentRunner())
    await service.select_task(100, "Тестовый пользователь", "problem_framing_task")
    await engine.dispose()

    second_engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    await init_db(second_engine)
    second_factory = create_session_factory(second_engine)
    async with second_factory() as session:
        user = await session.scalar(select(User).where(User.telegram_user_id == 100))
        state = await session.get(UserState, user.id)
    await second_engine.dispose()
    assert state.active_task_id == "problem_framing_task"


async def test_existing_v01_database_is_upgraded_without_manual_delete(tmp_path):
    db_path = tmp_path / "old.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, telegram_user_id BIGINT, display_name VARCHAR(255), created_at DATETIME, updated_at DATETIME)"))
        await conn.execute(text("CREATE TABLE user_state (user_id INTEGER PRIMARY KEY, active_task_id VARCHAR(120), rolling_summary TEXT, updated_at DATETIME)"))
        await conn.execute(text("CREATE TABLE task_progress (id INTEGER PRIMARY KEY, user_id INTEGER, task_id VARCHAR(120), status VARCHAR(20), notes TEXT, updated_at DATETIME)"))
    await engine.dispose()

    upgraded = create_engine(f"sqlite+aiosqlite:///{db_path}")
    await init_db(upgraded)
    async with upgraded.begin() as conn:
        user_state_columns = {
            row[1] for row in (await conn.execute(text("PRAGMA table_info(user_state)"))).fetchall()
        }
        task_progress_columns = {
            row[1] for row in (await conn.execute(text("PRAGMA table_info(task_progress)"))).fetchall()
        }
        tables = {
            row[0]
            for row in (
                await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            ).fetchall()
        }
    await upgraded.dispose()
    assert {"onboarding_status", "onboarding_skill_id"} <= user_state_columns
    assert {"attempt_count", "review_summary", "skill_evidence", "completed_at"} <= task_progress_columns
    assert "skill_assessments" in tables


async def test_incoming_message_and_reply_are_persisted(
    session_factory, task_service, prompt_builder
):
    runner = FakeAgentRunner(AssistantResult(reply="Разберём кейс.", rolling_summary="Кейс."))
    service = make_chat_service(session_factory, task_service, prompt_builder, runner)

    await service.process_user_message(100, "Тестовый пользователь", "Помоги с кейсом")

    async with session_factory() as session:
        messages = (await session.execute(select(Message).order_by(Message.id))).scalars().all()
    assert [(message.role, message.text) for message in messages] == [
        ("user", "Помоги с кейсом"),
        ("assistant", "Разберём кейс."),
    ]


async def test_each_request_calls_fresh_runner_without_resume(
    session_factory, task_service, prompt_builder
):
    runner = FakeAgentRunner()
    service = make_chat_service(session_factory, task_service, prompt_builder, runner)

    await service.process_user_message(100, "Тестовый пользователь", "Первое")
    await service.process_user_message(100, "Тестовый пользователь", "Второе")

    assert len(runner.prompts) == 2
    assert "resume" not in runner.prompts[0].lower()
    assert "resume" not in runner.prompts[1].lower()


async def test_timeout_or_runner_error_returns_fallback_and_next_message_works(
    session_factory, task_service, prompt_builder
):
    failing_runner = FakeAgentRunner(AgentRunError("timeout"))
    service = make_chat_service(session_factory, task_service, prompt_builder, failing_runner)

    failed = await service.process_user_message(100, "Тестовый пользователь", "Первое")

    working_runner = FakeAgentRunner(AssistantResult(reply="Теперь ок.", rolling_summary="Ок."))
    working_service = make_chat_service(
        session_factory, task_service, prompt_builder, working_runner
    )
    succeeded = await working_service.process_user_message(100, "Тестовый пользователь", "Второе")

    assert failed.reply == FALLBACK_REPLY
    assert succeeded.reply == "Теперь ок."


async def test_agent_memory_updates_reject_unknown_category(
    session_factory, task_service, prompt_builder
):
    runner = FakeAgentRunner(
        AssistantResult(
            reply="Не сохраняю случайное.",
            rolling_summary="Коротко.",
            memory_updates=[MemoryUpdate(key="random_phrase", value="hello")],
        )
    )
    service = make_chat_service(session_factory, task_service, prompt_builder, runner)

    await service.process_user_message(100, "Тестовый пользователь", "Привет")

    async with session_factory() as session:
        count = await session.scalar(select(func.count(MemoryItem.id)))
    assert count == 0


async def test_agent_memory_updates_are_persisted(session_factory, task_service, prompt_builder):
    runner = FakeAgentRunner(
        AssistantResult(
            reply="Запомнила.",
            rolling_summary="Пользователь работает над портфолио.",
            memory_updates=[MemoryUpdate(key="focus", value="portfolio")],
        )
    )
    service = make_chat_service(session_factory, task_service, prompt_builder, runner)

    await service.process_user_message(100, "Тестовый пользователь", "Я собираю портфолио")

    async with session_factory() as session:
        item = await session.scalar(select(MemoryItem).where(MemoryItem.key == "focus"))
    assert item.value == "portfolio"
