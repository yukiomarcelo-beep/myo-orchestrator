# NEXARA — Orquestrador Multi-Agente Jurídico

## Arquitetura

```
Entrada: PDF + tipo_demanda + objetivo (opcional)
         ↓
[1] Analisador (porta 8766)
    → extrai riscos com nível de criticidade
    → retorna ResultadoAnalisador (schema estruturado)
         ↓
[2] MotorQuerys (interno ao Orquestrador)
    → transforma riscos em queries direcionadas por tipo_demanda
    → prioriza riscos CRITICO → ALTO → MEDIO → BAIXO
         ↓
[3] Pesquisador (porta 8765)
    → recebe LoteQuerys com queries de jurisprudência + legislação
    → retorna ResultadoPesquisa por risco
         ↓
[4] Consolidador
    → Usuário escolhe: Unificado | Separados | Sumário Executivo
    → Gera .md (convertível para .docx via docx skill)
         ↓
[5] Persistência
    → logs/orquestracoes.jsonl (auditoria completa)
```

## Arquivos

| Arquivo                  | Responsabilidade                              |
|--------------------------|-----------------------------------------------|
| `schemas.py`             | Contratos de dados entre agentes (dataclasses)|
| `orquestrador.py`        | Pipeline principal + MotorQuerys + Consolidador|
| `orquestrador_server.py` | Servidor HTTP (8767) + CLI interativo         |

## Comandos

```bash
# Testar SEM crédito API (dry run)
python orquestrador_server.py --demo --dry-run

# Demo com API real
python orquestrador_server.py --demo

# Subir como servidor HTTP
python orquestrador_server.py --server
```

## Integração Cost Guard

Quando o crédito API estiver disponível, substituir chamadas diretas por:

```python
# Em orquestrador.py, ao chamar o Analisador e Pesquisador:
resultado = await guard.run(
    task_type="analise_contrato",   # haiku para validação, sonnet para análise
    prompt=payload,
    model_override=None             # cost_guard decide o modelo
)
```

## Variáveis de ambiente

```
ANALISADOR_URL=http://localhost:8766   # sobrescreve URL padrão
PESQUISADOR_URL=http://localhost:8765  # sobrescreve URL padrão
NEXARA_OUTPUT_DIR=outputs              # diretório de outputs
```

## Formatos de output

| Formato              | Arquivos gerados                                          |
|----------------------|-----------------------------------------------------------|
| `unificado`          | `nexara_*_relatorio_completo.md`                         |
| `separados`          | `*_analise_contrato.md` + `*_pesquisa_juridica.md` + `*_sumario_executivo.md` |
| `sumario`            | `nexara_*_sumario_executivo.md`                          |

## Schema de handoff Analisador → Orquestrador

O Analisador deve responder ao POST `/analisar` com:

```json
{
  "tipo_contrato": "Prestação de Serviços",
  "score_risco": 7.3,
  "riscos": [
    {
      "clausula": "Cláusula 5.2 — Rescisão",
      "descricao": "...",
      "nivel": "critico",
      "artigo_ref": "Art. 413 CC/2002"
    }
  ],
  "clausulas_ok": ["Cláusula 1 — Objeto"],
  "resumo_executivo": "..."
}
```

## Schema de handoff Orquestrador → Pesquisador

O Orquestrador envia ao POST `/pesquisar_lote`:

```json
{
  "queries": [
    {
      "risco_origem": "Cláusula 5.2 — Rescisão",
      "nivel_risco": "critico",
      "query_jurisprudencia": "rescisão antecipada multa STJ proporcionalidade",
      "query_legislacao": "Art. 413 CC/2002 texto vigente",
      "tribunais_alvo": ["STJ", "TJSP"]
    }
  ],
  "tipo_demanda": "prestacao_servicos",
  "objetivo": "revisar para assinar"
}
```

## Aviso jurídico

Todo relatório gerado inclui o disclaimer obrigatório:
> ⚠️ Este relatório foi produzido com auxílio de IA. Não substitui parecer de advogado habilitado.
