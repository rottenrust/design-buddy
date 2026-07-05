from dataclasses import dataclass
from pathlib import Path

from app.db.models import MemoryItem, Message, SkillAssessment, TaskProgress, UserState
from app.db.repositories import load_list
from app.services.task_service import Skill, Task


@dataclass(frozen=True)
class AgentContext:
    memory: list[MemoryItem]
    skills: list[Skill]
    skill_assessments: list[SkillAssessment]
    state: UserState
    active_task: Task | None
    active_task_progress: TaskProgress | None
    recent_messages: list[Message]
    user_message: str


class PromptBuilder:
    def __init__(self, system_prompt_path: Path) -> None:
        self.system_prompt_path = system_prompt_path

    def build(self, context: AgentContext) -> str:
        system_prompt = self.system_prompt_path.read_text(encoding="utf-8").strip()
        parts = [
            system_prompt,
            "",
            "Персональная память:",
            self._format_memory(context.memory),
            "",
            "Профиль навыков:",
            self._format_skill_profile(context.skills, context.skill_assessments),
            "",
            "Состояние первичного опроса:",
            self._format_onboarding(context.state),
            "",
            "Активное задание:",
            self._format_task(context.active_task, context.active_task_progress),
            "",
            "Краткое резюме диалога:",
            self._truncate(context.state.rolling_summary or "", 1500) or "Пока нет.",
            "",
            "Последние сообщения:",
            self._format_messages(context.recent_messages[-12:]),
            "",
            "Новое сообщение пользователя:",
            context.user_message,
            "",
            "Верни только JSON по схеме AssistantResult. Пользователю виден только reply. "
            "Не рассказывай о JSON, памяти, схемах, внутренних инструментах или технических "
            "обновлениях.",
        ]
        return "\n".join(parts)

    def _format_memory(self, memory: list[MemoryItem]) -> str:
        if not memory:
            return "Пока нет."
        return "\n".join(
            f"- {item.key}: {self._truncate(item.value, 500)}" for item in memory[:20]
        )

    def _format_skill_profile(
        self, skills: list[Skill], assessments: list[SkillAssessment]
    ) -> str:
        by_skill = {assessment.skill_id: assessment for assessment in assessments}
        lines: list[str] = []
        for skill in skills:
            assessment = by_skill.get(skill.id)
            if assessment is None:
                lines.append(f"- {skill.id} / {skill.title}: данных пока нет")
                continue
            strengths = ", ".join(load_list(assessment.strengths)) or "нет"
            gaps = ", ".join(load_list(assessment.gaps)) or "нет"
            lines.append(
                f"- {skill.id} / {skill.title}: self={assessment.self_level or 'unknown'}, "
                f"assessed={assessment.assessed_level}, confidence={assessment.confidence}; "
                f"evidence={self._truncate(assessment.evidence or 'нет', 300)}; "
                f"strengths={strengths}; gaps={gaps}"
            )
        return "\n".join(lines) if lines else "Пока нет."

    def _format_onboarding(self, state: UserState) -> str:
        return (
            f"status: {state.onboarding_status}\n"
            f"current_skill_id: {state.onboarding_skill_id or 'нет'}\n"
            "Если status не completed, веди короткий первичный опрос: один основной вопрос за ответ. "
            "Если данных достаточно по всем навыкам, предложи завершение через "
            "onboarding_completion_suggested."
        )

    def _format_task(self, task: Task | None, progress: TaskProgress | None) -> str:
        if task is None:
            return "Нет активного задания."
        deliverables = "\n".join(f"  - {item}" for item in task.deliverables)
        steps = "\n".join(f"  - {step}" for step in task.learning_steps)
        topics = "\n".join(f"  - {topic}" for topic in task.explanation_topics)
        rubric = "\n".join(f"  - {item.id}: {item.title}" for item in task.rubric)
        mistakes = "\n".join(f"  - {item}" for item in task.common_mistakes)
        notes = progress.notes if progress and progress.notes else "Пока нет."
        status = progress.status if progress else "not_started"
        return (
            f"{task.title}\n"
            f"id: {task.id}\n"
            f"skill_id: {task.skill_id}\n"
            f"status: {status}\n"
            f"attempt_count: {(progress.attempt_count if progress else 0) or 0}\n"
            f"why_it_matters: {task.why_it_matters}\n"
            f"context: {task.context}\n"
            f"brief: {task.brief}\n"
            f"deliverables:\n{deliverables}\n"
            f"learning_steps:\n{steps}\n"
            f"explanation_topics:\n{topics}\n"
            f"rubric:\n{rubric}\n"
            f"common_mistakes:\n{mistakes}\n"
            f"done_definition: {task.done_definition}\n"
            f"review_summary: {self._truncate((progress.review_summary if progress else '') or 'Пока нет.', 800)}\n"
            f"skill_evidence: {self._truncate((progress.skill_evidence if progress else '') or 'Пока нет.', 800)}\n"
            f"notes:\n{self._truncate(notes, 1500)}"
        )

    def _format_messages(self, messages: list[Message]) -> str:
        if not messages:
            return "Пока нет."
        return "\n".join(f"{message.role}: {message.text}" for message in messages[-12:])

    def _truncate(self, text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"
