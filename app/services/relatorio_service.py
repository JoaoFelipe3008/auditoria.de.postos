"""
relatorio_service.py — Geração de relatórios de auditoria.

Formatos de saída:
  - TXT  : relatório legível no terminal e em arquivos .txt
  - CSV  : tabela de divergências para importação em Excel/BI
  - JSON : saída estruturada para integração com sistemas

O módulo é completamente determinístico — não usa IA para os cálculos.
Os textos de causa e recomendação já vêm preenchidos pelas regras de negócio.
"""

from __future__ import annotations

import csv
import json
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from app.models.schemas import (
    Divergencia,
    NivelRisco,
    ResultadoAuditoria,
    TipoDivergencia,
)

logger = logging.getLogger(__name__)

# Ícones de risco para o relatório textual
_ICONE_RISCO = {
    NivelRisco.BAIXO: "[ BAIXO  ]",
    NivelRisco.MEDIO: "[ MÉDIO  ]",
    NivelRisco.ALTO:  "[ ALTO   ]",
    NivelRisco.CRITICO: "[CRÍTICO ]",
}

_SEPARADOR = "=" * 80
_SEPARADOR_FINO = "-" * 80


# ---------------------------------------------------------------------------
# Formatadores auxiliares
# ---------------------------------------------------------------------------

def _linha_divergencia(div: Divergencia, idx: int) -> str:
    icone = _ICONE_RISCO.get(div.nivel_risco, "[???????]")
    return (
        f"  {idx:02d}. {icone} [{div.tipo.value}] {div.referencia} — {div.descricao}\n"
        f"      Causa provável : {div.causa_provavel}\n"
        f"      Recomendação   : {div.recomendacao}\n"
    )


def _resumo_tipo(divs: List[Divergencia], tipo: TipoDivergencia) -> str:
    filtradas = [d for d in divs if d.tipo == tipo]
    if not filtradas:
        return f"  {tipo.value}: NENHUMA divergência encontrada.\n"
    return f"  {tipo.value}: {len(filtradas)} divergência(s)\n"


def _barra_score(score: float) -> str:
    """Barra visual de conformidade de 0 a 100."""
    preenchidos = int(score / 5)   # 20 blocos para 100%
    barra = "█" * preenchidos + "░" * (20 - preenchidos)
    return f"[{barra}] {score:.1f}%"


# ---------------------------------------------------------------------------
# Relatório TXT
# ---------------------------------------------------------------------------

def gerar_relatorio_txt(resultado: ResultadoAuditoria) -> str:
    """Gera o relatório completo em formato texto."""
    linhas: List[str] = []

    # Cabeçalho
    linhas.append(_SEPARADOR)
    linhas.append(f"  RELATÓRIO DE AUDITORIA OPERACIONAL — POSTOS DE COMBUSTÍVEIS")
    linhas.append(_SEPARADOR)
    linhas.append(f"  Posto          : {resultado.posto}")
    linhas.append(f"  Data auditoria : {resultado.data_auditoria.strftime('%d/%m/%Y')}")
    linhas.append(f"  Gerado em      : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    linhas.append(_SEPARADOR_FINO)

    # Resumo executivo
    linhas.append("")
    linhas.append("  RESUMO EXECUTIVO")
    linhas.append(_SEPARADOR_FINO)
    linhas.append(f"  Score de Conformidade  : {_barra_score(resultado.score_conformidade)}")
    linhas.append(f"  Total de Divergências  : {resultado.total_divergencias}")
    linhas.append(f"  Divergências ALTO RISCO: {resultado.divergencias_alto_risco}")
    linhas.append(f"  Divergências CRÍTICAS  : {resultado.divergencias_criticas}")
    linhas.append("")
    linhas.append("  POR MÓDULO:")
    linhas.append(_resumo_tipo(resultado.divergencias, TipoDivergencia.LMC))
    linhas.append(_resumo_tipo(resultado.divergencias, TipoDivergencia.PERDA_SOBRA))
    linhas.append(_resumo_tipo(resultado.divergencias, TipoDivergencia.CAIXA))
    linhas.append(_resumo_tipo(resultado.divergencias, TipoDivergencia.AFERICAO))

    if resultado.total_divergencias == 0:
        linhas.append("")
        linhas.append("  ✓ NENHUMA DIVERGÊNCIA ENCONTRADA — Operação dentro dos parâmetros.")
        linhas.append(_SEPARADOR)
        return "\n".join(linhas)

    # Detalhamento por módulo
    for tipo in TipoDivergencia:
        divs_tipo = [d for d in resultado.divergencias if d.tipo == tipo]
        if not divs_tipo:
            continue

        linhas.append("")
        linhas.append(_SEPARADOR_FINO)
        linhas.append(f"  DETALHAMENTO — {tipo.value}")
        linhas.append(_SEPARADOR_FINO)

        for i, div in enumerate(divs_tipo, start=1):
            linhas.append(_linha_divergencia(div, i))

    # Ranking de divergências por severidade
    linhas.append(_SEPARADOR_FINO)
    linhas.append("  AÇÕES PRIORITÁRIAS (por ordem de risco)")
    linhas.append(_SEPARADOR_FINO)

    ordem_risco = [NivelRisco.CRITICO, NivelRisco.ALTO, NivelRisco.MEDIO, NivelRisco.BAIXO]
    idx = 1
    for nivel in ordem_risco:
        for div in resultado.divergencias:
            if div.nivel_risco == nivel:
                icone = _ICONE_RISCO[nivel]
                linhas.append(
                    f"  {idx:02d}. {icone} [{div.tipo.value}] {div.referencia} ({div.data})"
                )
                linhas.append(f"       → {div.recomendacao}")
                linhas.append("")
                idx += 1

    # Rodapé
    linhas.append(_SEPARADOR)
    linhas.append("  Documento gerado automaticamente pelo Sistema de Auditoria Operacional.")
    linhas.append("  Este relatório é confidencial e destinado exclusivamente à gestão do posto.")
    linhas.append(_SEPARADOR)

    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Relatório CSV
# ---------------------------------------------------------------------------

def gerar_relatorio_csv(resultado: ResultadoAuditoria) -> str:
    """Gera CSV com todas as divergências (uma linha por divergência)."""
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", quoting=csv.QUOTE_ALL)

    # Cabeçalho
    writer.writerow([
        "posto",
        "data_auditoria",
        "tipo",
        "data_ocorrencia",
        "referencia",
        "nivel_risco",
        "descricao",
        "valor_esperado",
        "valor_informado",
        "diferenca",
        "diferenca_absoluta",
        "causa_provavel",
        "recomendacao",
    ])

    for div in resultado.divergencias:
        writer.writerow([
            resultado.posto,
            resultado.data_auditoria.strftime("%Y-%m-%d"),
            div.tipo.value,
            div.data.strftime("%Y-%m-%d"),
            div.referencia,
            div.nivel_risco.value,
            div.descricao,
            f"{div.valor_esperado:.4f}".replace(".", ","),
            f"{div.valor_informado:.4f}".replace(".", ","),
            f"{div.diferenca:.4f}".replace(".", ","),
            f"{div.diferenca_absoluta:.4f}".replace(".", ","),
            div.causa_provavel,
            div.recomendacao,
        ])

    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Relatório JSON
# ---------------------------------------------------------------------------

def gerar_relatorio_json(resultado: ResultadoAuditoria) -> str:
    """Gera JSON estruturado — ideal para integrações e APIs futuras."""

    def div_to_dict(div: Divergencia) -> dict:
        return {
            "tipo": div.tipo.value,
            "data": div.data.isoformat(),
            "referencia": div.referencia,
            "nivel_risco": div.nivel_risco.value,
            "descricao": div.descricao,
            "valor_esperado": div.valor_esperado,
            "valor_informado": div.valor_informado,
            "diferenca": div.diferenca,
            "diferenca_absoluta": div.diferenca_absoluta,
            "causa_provavel": div.causa_provavel,
            "recomendacao": div.recomendacao,
            "posto": div.posto,
        }

    payload = {
        "auditoria": {
            "posto": resultado.posto,
            "data_auditoria": resultado.data_auditoria.isoformat(),
            "gerado_em": datetime.now().isoformat(),
        },
        "metricas": {
            "score_conformidade": resultado.score_conformidade,
            "total_divergencias": resultado.total_divergencias,
            "divergencias_alto_risco": resultado.divergencias_alto_risco,
            "divergencias_criticas": resultado.divergencias_criticas,
        },
        "divergencias": [div_to_dict(d) for d in resultado.divergencias],
    }

    return json.dumps(payload, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Persistência em disco
# ---------------------------------------------------------------------------

class RelatorioService:
    """
    Gerencia a geração e persistência dos relatórios de auditoria.

    Uso:
        svc = RelatorioService(pasta_saida=Path("data/relatorios"))
        svc.salvar_todos(resultado)
    """

    def __init__(self, pasta_saida: Path) -> None:
        self.pasta_saida = pasta_saida
        self.pasta_saida.mkdir(parents=True, exist_ok=True)

    def _prefixo(self, resultado: ResultadoAuditoria) -> str:
        posto_slug = resultado.posto.lower().replace(" ", "_")
        data_str = resultado.data_auditoria.strftime("%Y%m%d")
        ts = datetime.now().strftime("%H%M%S")
        return f"{data_str}_{ts}_{posto_slug}"

    def salvar_txt(self, resultado: ResultadoAuditoria) -> Path:
        conteudo = gerar_relatorio_txt(resultado)
        caminho = self.pasta_saida / f"{self._prefixo(resultado)}_relatorio.txt"
        caminho.write_text(conteudo, encoding="utf-8")
        logger.info("Relatório TXT salvo em: %s", caminho)
        return caminho

    def salvar_csv(self, resultado: ResultadoAuditoria) -> Path:
        conteudo = gerar_relatorio_csv(resultado)
        caminho = self.pasta_saida / f"{self._prefixo(resultado)}_divergencias.csv"
        caminho.write_text(conteudo, encoding="utf-8-sig")   # UTF-8 BOM para Excel
        logger.info("Relatório CSV salvo em: %s", caminho)
        return caminho

    def salvar_json(self, resultado: ResultadoAuditoria) -> Path:
        conteudo = gerar_relatorio_json(resultado)
        caminho = self.pasta_saida / f"{self._prefixo(resultado)}_auditoria.json"
        caminho.write_text(conteudo, encoding="utf-8")
        logger.info("Relatório JSON salvo em: %s", caminho)
        return caminho

    def salvar_todos(self, resultado: ResultadoAuditoria) -> dict[str, Path]:
        """Gera e salva todos os formatos de relatório."""
        return {
            "txt":  self.salvar_txt(resultado),
            "csv":  self.salvar_csv(resultado),
            "json": self.salvar_json(resultado),
        }

    def imprimir_no_terminal(self, resultado: ResultadoAuditoria) -> None:
        """Exibe o relatório TXT diretamente no stdout."""
        print(gerar_relatorio_txt(resultado))

    @staticmethod
    def resumo_multi_posto(resultados: List[ResultadoAuditoria]) -> str:
        """Gera resumo consolidado de múltiplos postos."""
        linhas: List[str] = []
        linhas.append(_SEPARADOR)
        linhas.append("  RESUMO CONSOLIDADO — MÚLTIPLOS POSTOS")
        linhas.append(_SEPARADOR)

        for r in sorted(resultados, key=lambda x: x.score_conformidade):
            status = "⚠ ATENÇÃO" if r.score_conformidade < 70 else "✓ OK"
            linhas.append(
                f"  {status}  {r.posto:<30} "
                f"Score: {_barra_score(r.score_conformidade)}  "
                f"Divergências: {r.total_divergencias}"
            )

        linhas.append(_SEPARADOR)
        return "\n".join(linhas)
