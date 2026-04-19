"""
Aviso obrigatório hardcoded no código — não nas regras.
Resolve: aviso dependia de disciplina humana.
Dois modos: interno (advogado) e cliente (documento final).
"""
from datetime import datetime
from typing import Literal

ModoAviso = Literal["interno", "cliente"]

class AvisoJuridico:
    _INTERNO = """
---
> ⚠️ **DOCUMENTO DE USO INTERNO — REVISÃO OBRIGATÓRIA**
>
> Este relatório foi gerado automaticamente pelo sistema **Nexara** com uso de
> Inteligência Artificial. Não constitui parecer jurídico e não substitui a
> análise de advogado habilitado.
>
> **Antes de qualquer uso externo:** revisar riscos sinalizados, verificar
> atualidade das referências legais e aprovar formalmente o documento.
>
> Gerado em: {data_hora} | Checklist: v{checklist_versao} | {modelo}
---""".strip()

    _CLIENTE = """
---
*Este documento foi preparado com auxílio de ferramentas tecnológicas de análise
jurídica e revisado por profissional habilitado. Data: {data}.*
---""".strip()

    @classmethod
    def para_relatorio(cls, tipo_analise: str, checklist_versao: str = "1.0.0",
                       modo: ModoAviso = "interno",
                       modelo: str = "claude-sonnet-4-6") -> str:
        agora = datetime.now()
        if modo == "interno":
            return cls._INTERNO.format(
                data_hora=agora.strftime("%d/%m/%Y às %H:%M"),
                checklist_versao=checklist_versao, modelo=modelo)
        return cls._CLIENTE.format(data=agora.strftime("%d/%m/%Y"))

    @classmethod
    def inserir_no_relatorio(cls, conteudo: str = "", tipo_analise: str = "",
                              checklist_versao: str = "1.0.0",
                              modo: ModoAviso = "interno",
                              modelo: str = "claude-sonnet-4-6",
                              posicao: Literal["topo", "rodape"] = "topo",
                              conteudo_relatorio: str = "") -> str:
        texto = conteudo_relatorio or conteudo
        aviso = cls.para_relatorio(tipo_analise, checklist_versao, modo, modelo)
        return f"{aviso}\n\n{texto}" if posicao == "topo" else f"{texto}\n\n{aviso}"

    @classmethod
    def validar_conteudo(cls, conteudo: str) -> bool:
        return any(m in conteudo for m in ["DOCUMENTO DE USO INTERNO", "Nexara",
                                            "ferramentas tecnológicas"])
