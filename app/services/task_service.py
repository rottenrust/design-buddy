from collections import Counter
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Skill(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    order: int
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    diagnostic_questions: list[str] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TaskRubricItem(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Task(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    skill_id: str = Field(min_length=1, max_length=120)
    order: int
    title: str = Field(min_length=1)
    why_it_matters: str = Field(min_length=1)
    context: str = Field(min_length=1)
    brief: str = Field(min_length=1)
    deliverables: list[str] = Field(min_length=1)
    learning_steps: list[str] = Field(min_length=1)
    explanation_topics: list[str] = Field(min_length=1)
    rubric: list[TaskRubricItem] = Field(min_length=1)
    common_mistakes: list[str] = Field(min_length=1)
    done_definition: str = Field(min_length=1)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TaskCatalog(BaseModel):
    skills: list[Skill] = Field(min_length=1)
    tasks: list[Task] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_catalog(self) -> "TaskCatalog":
        skill_ids = [skill.id for skill in self.skills]
        task_ids = [task.id for task in self.tasks]
        if len(skill_ids) != len(set(skill_ids)):
            raise ValueError("skill ids must be unique")
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("task ids must be unique")

        known_skill_ids = set(skill_ids)
        unknown_skill_ids = sorted({task.skill_id for task in self.tasks} - known_skill_ids)
        if unknown_skill_ids:
            raise ValueError(f"unknown task skill_id: {', '.join(unknown_skill_ids)}")

        task_counts = Counter(task.skill_id for task in self.tasks)
        missing = sorted(known_skill_ids - set(task_counts))
        duplicated = sorted(skill_id for skill_id, count in task_counts.items() if count != 1)
        if missing:
            raise ValueError(f"skills without tasks: {', '.join(missing)}")
        if duplicated:
            raise ValueError(f"skills must have exactly one task: {', '.join(duplicated)}")

        self.skills.sort(key=lambda skill: skill.order)
        self.tasks.sort(key=lambda task: task.order)
        return self


class TaskService:
    def __init__(self, tasks_path: Path) -> None:
        self.tasks_path = tasks_path
        self._catalog: TaskCatalog | None = None

    def load_catalog(self) -> TaskCatalog:
        if self._catalog is None:
            data = yaml.safe_load(self.tasks_path.read_text(encoding="utf-8"))
            self._catalog = TaskCatalog.model_validate(data)
        return self._catalog

    def list_skills(self) -> list[Skill]:
        return list(self.load_catalog().skills)

    def list_tasks(self) -> list[Task]:
        return list(self.load_catalog().tasks)

    def get_skill(self, skill_id: str | None) -> Skill | None:
        if skill_id is None:
            return None
        return next((skill for skill in self.list_skills() if skill.id == skill_id), None)

    def get_task(self, task_id: str | None) -> Task | None:
        if task_id is None:
            return None
        return next((task for task in self.list_tasks() if task.id == task_id), None)

    def get_task_for_skill(self, skill_id: str) -> Task | None:
        return next((task for task in self.list_tasks() if task.skill_id == skill_id), None)

    def known_skill_ids(self) -> set[str]:
        return {skill.id for skill in self.list_skills()}
