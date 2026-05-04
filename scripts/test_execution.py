from engines.execution_engine import AgentType, ExecutionEngine, TaskPriority, TaskType

engine = ExecutionEngine()

task = engine.create_task(
    title="Teste inicial MYO",
    description="Criando primeira task para validar execution_engine",
    origin_engine="test",
    task_type=TaskType.CODE,
    priority=TaskPriority.HIGH,
    suggested_agent=AgentType.CLAUDE,
    context={"teste": True},
    acceptance_criteria=["Task criada com sucesso"],
    deliverables=["Arquivo JSON gerado"],
    tags=["teste"],
)

print("TASK CRIADA:")
print(task)
