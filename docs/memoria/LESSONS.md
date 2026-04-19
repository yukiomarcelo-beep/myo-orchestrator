# MYO · Lessons Learned

Registro de problemas encontrados, causas-raiz e soluções.
**Ler antes de abrir novo chat com Claude sobre MYO.**

---

## LESSON-001 · `_fix_indent.py` destruiu 3 arquivos do trust pipeline

**Data:** 2026-04-18 · **Severidade:** CRITICAL
**Arquivos:** `utils/verification_engine.py`, `utils/verification_logger.py`, `policies/policy_adapter.py`

### Problema
Script `_fix_indent.py` foi rodado pra "consertar indentação". Resultado:
- `verification_engine` e `verification_logger`: métodos re-aninhados dentro de `__init__` (inacessíveis), corpos de if/else/for substituídos por blocos gigantes de `pass`. Compilam mas não executam.
- `policy_adapter`: indentação de 1 espaço + `continue` fora de `for`. AST parse passava, execução falhava.

Todos os 3 formavam o trust pipeline. Quebra coordenada, invisível.

### Causa-raiz
Scripts de formatação automática que re-indentam linha por linha sem entender escopo. Onde ficam ambíguos, substituem corpo por `pass` e reaninham funções em escopos errados.

### Solução
Reparo cirúrgico em sandbox (sem reescrita de lógica):
1. `ast.parse()` mapeia estrutura real
2. Detecta blocos de `pass` consecutivos (assinatura do dano)
3. Remove blocos, re-indenta pra 4 espaços padrão
4. Métodos voltam a ser filhos diretos da classe
5. Teste de fumaça: instanciação + chamada de métodos + integração end-to-end

Resultados:
- `verification_engine.py`: 2579 → 591 linhas (1989 passes removidos)
- `verification_logger.py`: 2137 → 162 linhas (1983 passes removidos)
- `policy_adapter.py`: 376 → 412 linhas (indentação normalizada)

### Prevenção
- Nunca rodar auto-fix de indentação em arquivos críticos sem backup + smoke test depois
- Smoke test obrigatório por módulo crítico no CI:
  ```python
  def test_verification_engine_methods_accessible():
      e = VerificationEngine()
      for m in ['verify', 'generate_validation_tasks', '_execution_gate']:
          assert callable(getattr(e, m))
  ```
- Alerta operacional: se `verification_events.jsonl` parar de crescer por >24h, trust pipeline morreu. Integrar ao health_score.

### Como detectar em outros arquivos
```bash
cd ~/Documents/orchestrator && \
for f in $(find . -name "*.py" -not -path "*/venv/*" -not -path "*/.claude/*"); do
  max=$(python3 -c "
lines = open('$f').readlines()
run = mx = 0
for l in lines:
    if l.strip() == 'pass': run += 1; mx = max(mx, run)
    else: run = 0
print(mx)
  " 2>/dev/null)
  if [ "$max" -gt 5 ]; then echo "⚠  $f: $max passes"; fi
done
```

---

## LESSON-002 · Engines não passavam `execution_context` pro verification_engine

**Data:** 2026-04-18 · **Severidade:** MEDIUM
**Arquivos:** qualquer engine que chama `VerificationEngine.verify()`

### Problema
Dos 46 eventos históricos em `verification_events.jsonl`:
- 45 com `execution_context="unknown"`
- 1 com contexto válido (teste de hoje)

`policy_adapter` agrupa ajustes por contexto (idea/research/mvp/launch_ready/scaling). Se 99% dos eventos caem em `unknown`, adapter nunca tem evidência suficiente por contexto real. 6C Context-Aware Policy vira no-op.

### Causa-raiz
Chamadas como `engine.verify(text=..., origin_engine="product_engine")` sem passar `execution_context`. O param existe mas não é usado. Logger grava `"unknown"` como fallback, mascarando o problema.

### Solução (pendente)
1. Grep todos os call-sites de `engine.verify(`
2. Identificar o contexto de cada engine:
   - `product_engine` → idea/research/mvp (depende da fase do produto)
   - `content_engine` → launch_ready/scaling
   - `research_engine` → research
3. Passar `execution_context` em cada chamada
4. Eventos legados em `unknown` ficam como histórico

### Prevenção
- Smoke test: todo `verify()` por engine passa contexto válido
- WARNING no logger se `execution_context == "unknown"` + origin_engine, pra visibilidade em dev

---

## LESSON-003 · Trust pipeline tinha histórico real anterior ao dano

**Data:** 2026-04-18 · **Severidade:** INFO

### Descoberta
Ao religar o pipeline (reparo dos 3 módulos), descobrimos 45 eventos legados em `verification_events.jsonl` de antes do `_fix_indent.py` rodar. Distribuição:

| Tópico | Fail rate | N |
|---|---|---|
| api_cost | 38% | 8 |
| competitor | 33% | 3 |
| market_data | 33% | 3 |
| pricing | 25% | 8 |
| demand | 25% | 4 |
| timing | 12% | 8 |
| strategy | 0% | 4 |
| headline_copy | 0% | 7 |

### Valor
Mesmo antes do 6C funcionar (contexto="unknown"), o histórico revela tópicos com risco real:
- `api_cost` com 38% de falha em 8 eventos = sinal de que claims sobre custo de API são sistematicamente mal-suportadas
- `pricing` com 25% em 8 eventos = preços tendem a ser chutes

Quando LESSON-002 for resolvida e eventos novos tiverem contexto, o policy_adapter vai poder ajustar thresholds com base em evidência real — não precisa começar do zero.

---

## Template pra próximas lições

```markdown
## LESSON-NNN · [Título curto]

**Data:** YYYY-MM-DD · **Severidade:** LOW | MEDIUM | HIGH | CRITICAL
**Arquivos:** path(s)

### Problema
O que aconteceu.

### Causa-raiz
Por que aconteceu.

### Solução
O que foi feito.

### Prevenção
Como evitar repetir.
```
