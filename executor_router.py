"""
Executor Router — Pipeline AI
Recebe uma ExecutionTask e roteia para o executor correto conforme o canal.

Canais suportados:
 GITHUB → github_executor.create_github_issue
 LOCAL → salva localmente, sem despacho externo
 N8N → stub (não implementado)

Adicionar novos executores aqui sem tocar no execution_engine.
"""
from execution_engine import ExecutionTask, ExecutionChannel


async def route(task: ExecutionTask) -> dict:
    """
    Roteia a task para o executor correto.
    Retorna dict com pelo menos { status }.
    """
    channel = task.execution_channel

    if channel == ExecutionChannel.GITHUB:
        return await _dispatch_github(task)

    if channel == ExecutionChannel.LOCAL:
        return _dispatch_local(task)

    if channel == ExecutionChannel.N8N:
        return await _dispatch_n8n(task)

    raise ValueError(f"[executor_router] Canal desconhecido: {channel}")


# Executores

async def _dispatch_github(task: ExecutionTask) -> dict:
    from github_executor import create_github_issue
    return await create_github_issue(task)


def _dispatch_local(task: ExecutionTask) -> dict:
    """
    Task local: já foi salva em disco pelo execution_engine.
    Retorna confirmação sem abrir canal externo.
    """
    print(f"[executor_router] Task local confirmada: {task.task_id}")
    return {
        "status": "local",
        "message": f"Task {task.task_id} salva localmente. Nenhum canal externo acionado.",
    }


async def _dispatch_n8n(task: ExecutionTask) -> dict:
    raise NotImplementedError(
        "[executor_router] N8N executor ainda não implementado. "
        "Configure WEBHOOK_N8N no .env e implemente _dispatch_n8n."
    )
