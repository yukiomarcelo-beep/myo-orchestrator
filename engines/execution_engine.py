import asyncio
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

# =========================
# ENUMS
# =========================


class TaskPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TaskStatus(str, Enum):
    PENDING = "pending"
    ROUTED = "routed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class ExecutionChannel(str, Enum):
    GITHUB = "github"
    LOCAL = "local"
    N8N = "n8n"


class AgentType(str, Enum):
    CLAUDE = "claude"
    CODEX = "codex"
    COPILOT = "copilot"
    GPT = "gpt"
    HUMAN = "human"


class TaskType(str, Enum):
    RESEARCH = "research"
    COPY = "copy"
    CODE = "code"
    REVIEW = "review"
    AUTOMATION = "automation"
    ANALYSIS = "analysis"
    VALIDATION = "validation"


# =========================
# DATA MODEL
# =========================


@dataclass
class ExecutionTask:
    task_id: str
    title: str
    description: str
    origin_engine: str
    task_type: TaskType
    priority: TaskPriority
    suggested_agent: AgentType
    execution_channel: ExecutionChannel

    origin_run_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    related_entity_id: Optional[str] = None

    status: TaskStatus = TaskStatus.PENDING
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    # Gate duplo: approved = conceitualmente bom, execution_ready = apto para despacho externo
    execution_ready: bool = False

    context: Dict[str, Any] = field(default_factory=dict)
    acceptance_criteria: List[str] = field(default_factory=list)
    deliverables: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    result_summary: Optional[str] = None
    next_action: Optional[str] = None

    # Preenchidos após despacho externo
    issue_number: Optional[int] = None
    issue_url: Optional[str] = None

    # Rastreabilidade de despacho
    dispatch_status: Optional[str] = None  # "success" | "failed" | "skipped"
    dispatch_error: Optional[str] = None
    dispatched_at: Optional[str] = None

    # Metadados de retry/experimento (preenchidos pelo myo_cli ao fazer retry)
    original_failure_type: Optional[str] = (
        None  # policy_rigidity | agent_instability | bad_source | unknown
    )
    retry_mode: Optional[str] = None  # direct | experiment
    experiment_context: Optional[str] = None  # research | launch_ready | etc.
    experiment_result: Optional[str] = None  # success | failed
    original_hint: Optional[str] = None


# =========================
# ENGINE
# =========================


class ExecutionEngine:
    def __init__(self, base_dir: str = "outputs/execution_tasks"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def generate_task_id(self) -> str:
        return f"task_{uuid.uuid4().hex[:12]}"

    def save_task(self, task: ExecutionTask) -> Path:
        filepath = self.base_dir / f"{task.task_id}.json"

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(asdict(task), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[ERRO] Falha ao salvar task: {e}")
            raise

        print(f"[OK] Task salva em: {filepath}")
        return filepath

    def route_task(self, task: ExecutionTask) -> ExecutionTask:
        if task.task_type in {TaskType.CODE, TaskType.AUTOMATION}:
            task.execution_channel = ExecutionChannel.GITHUB

            if task.suggested_agent not in {
                AgentType.CODEX,
                AgentType.CLAUDE,
                AgentType.COPILOT,
            }:
                task.suggested_agent = AgentType.CODEX

        elif task.task_type in {
            TaskType.COPY,
            TaskType.RESEARCH,
            TaskType.ANALYSIS,
        }:
            task.execution_channel = ExecutionChannel.LOCAL

        elif task.task_type == TaskType.REVIEW:
            task.execution_channel = ExecutionChannel.GITHUB

            if task.suggested_agent == AgentType.HUMAN:
                task.suggested_agent = AgentType.CLAUDE

        task.status = TaskStatus.ROUTED
        return task

    def create_task(
        self,
        title: str,
        description: str,
        origin_engine: str,
        task_type: TaskType,
        priority: TaskPriority,
        suggested_agent: AgentType,
        execution_channel: ExecutionChannel = ExecutionChannel.LOCAL,
        execution_ready: bool = False,
        origin_run_id: Optional[str] = None,
        parent_task_id: Optional[str] = None,
        related_entity_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        acceptance_criteria: Optional[List[str]] = None,
        deliverables: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
    ) -> ExecutionTask:
        task = ExecutionTask(
            task_id=self.generate_task_id(),
            title=title,
            description=description,
            origin_engine=origin_engine,
            task_type=task_type,
            priority=priority,
            suggested_agent=suggested_agent,
            execution_channel=execution_channel,
            execution_ready=execution_ready,
            origin_run_id=origin_run_id,
            parent_task_id=parent_task_id,
            related_entity_id=related_entity_id,
            context=context or {},
            acceptance_criteria=acceptance_criteria or [],
            deliverables=deliverables or [],
            tags=tags or [],
        )

        print(f"[INFO] Criando task: {task.title}")

        task = self.route_task(task)

        self.save_task(task)

        print(
            f"[INFO] Task roteada para: {task.execution_channel} | agente: {task.suggested_agent} | execution_ready: {task.execution_ready}"
        )

        return task

    async def dispatch_task(self, task: ExecutionTask, max_attempts: int = 2) -> ExecutionTask:
        """
        Despacha a task para o canal externo via executor_router.
        Só age se execution_ready=True.
        Tenta até max_attempts vezes antes de marcar como falha.
        """
        if not task.execution_ready:
            print(f"[INFO] Task {task.task_id} não está execution_ready. Despacho ignorado.")
            task.dispatch_status = "skipped"
            self.save_task(task)
            return task

        from api.executor_router import route

        last_error: Optional[str] = None

        for attempt in range(1, max_attempts + 1):
            try:
                print(
                    f"[INFO] Despachando task {task.task_id} (tentativa {attempt}/{max_attempts}): {task.title}"
                )
                result = await route(task)
                task.issue_number = result.get("issue_number")
                task.issue_url = result.get("issue_url")
                task.dispatch_status = "success"
                task.dispatch_error = None
                task.dispatched_at = datetime.utcnow().isoformat()
                task.status = TaskStatus.IN_PROGRESS
                self.save_task(task)
                print(f"[OK] Despacho concluído: {result}")
                return task
            except Exception as e:
                last_error = str(e)
                print(f"[AVISO] Tentativa {attempt} falhou: {last_error}")
                if attempt < max_attempts:
                    await asyncio.sleep(3)

        task.dispatch_status = "failed"
        task.dispatch_error = last_error
        task.dispatched_at = datetime.utcnow().isoformat()
        self.save_task(task)
        print(f"[ERRO] Despacho falhou após {max_attempts} tentativas: {last_error}")
        return task
