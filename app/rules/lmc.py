"""
lmc.py — Regras de negócio para auditoria do LMC (Livro de Movimentação de Combustíveis).

Regras aplicadas:
  R1 — Balanço de estoque: estoque_final_esperado = estoque_inicial + entradas - vendas
  R2 — Estoque negativo: estoque_final informado não pode ser negativo
  R3 — Entradas sem venda: tanque com entrada mas sem nenhuma venda no período (provável esquecimento)
  R4 — Variação extrema de vendas: queda ou pico acima de 80% em relação à média histórica do tanque
"""

from __future__ import annotations

import logging
from datetime import date
from typing import List

import numpy as np

from app.models.schemas import (
    ConfiguracaoTolerancia,
    Divergencia,
    NivelRisco,
    RegistroLMC,
    TipoDivergencia,
    TOLERANCIAS_PADRAO,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Classificação de risco por magnitude da diferença
# ---------------------------------------------------------------------------

def _classificar_risco_lmc(diferenca_abs: float, cfg: ConfiguracaoTolerancia) -> NivelRisco:
    if diferenca_abs <= cfg.lmc_tolerancia_baixo:
        return NivelRisco.BAIXO
    if diferenca_abs <= cfg.lmc_tolerancia_medio:
        return NivelRisco.MEDIO
    if diferenca_abs <= cfg.lmc_tolerancia_alto:
        return NivelRisco.ALTO
    return NivelRisco.CRITICO


# ---------------------------------------------------------------------------
# Causas e recomendações parametrizadas
# ---------------------------------------------------------------------------

def _causa_balanco(diferenca: float, tanque: str) -> str:
    if diferenca > 0:
        return (
            f"Estoque final do {tanque} está MENOR que o esperado. "
            "Possível perda por evaporação acima do normal, vazamento, "
            "desvio de combustível ou erro de lançamento das vendas."
        )
    return (
        f"Estoque final do {tanque} está MAIOR que o esperado. "
        "Possível erro na medição do estoque, entrada de combustível não registrada "
        "ou lançamento de vendas a menor que o real."
    )


def _recomendacao_balanco(diferenca: float, nivel: NivelRisco, tanque: str) -> str:
    base = f"Revisar todos os lançamentos do {tanque} no período."
    if nivel in (NivelRisco.ALTO, NivelRisco.CRITICO):
        if diferenca > 0:
            return (
                base
                + " Inspecionar fisicamente o tanque e as mangueiras para vazamento. "
                "Cruzar volumes das bombas com o estoque. Acionar manutenção preventiva."
            )
        return (
            base
            + " Verificar notas fiscais de entrada não registradas. "
            "Confirmar medição física do estoque inicial."
        )
    return base + " Confirmar medição do dipstick e relançar se necessário."


# ---------------------------------------------------------------------------
# Regra R1 — Balanço de estoque
# ---------------------------------------------------------------------------

def auditar_balanco(
    registros: List[RegistroLMC],
    cfg: ConfiguracaoTolerancia = TOLERANCIAS_PADRAO,
) -> List[Divergencia]:
    """
    Verifica se estoque_final == estoque_inicial + entradas - vendas.
    Divergências abaixo de 5 litros são ignoradas (margem de medição de dipstick).
    """
    MARGEM_MINIMA = 5.0  # litros — ruído de leitura de dipstick
    divergencias: List[Divergencia] = []

    for reg in registros:
        esperado = reg.estoque_inicial + reg.entradas - reg.vendas
        diferenca = esperado - reg.estoque_final

        if abs(diferenca) <= MARGEM_MINIMA:
            continue

        nivel = _classificar_risco_lmc(abs(diferenca), cfg)

        div = Divergencia(
            tipo=TipoDivergencia.LMC,
            data=reg.data,
            referencia=reg.tanque,
            descricao=(
                f"Divergência no balanço do {reg.tanque}: "
                f"esperado {esperado:.1f} L, informado {reg.estoque_final:.1f} L "
                f"(diferença de {diferenca:+.1f} L)"
            ),
            valor_esperado=round(esperado, 2),
            valor_informado=round(reg.estoque_final, 2),
            diferenca=round(diferenca, 2),
            nivel_risco=nivel,
            causa_provavel=_causa_balanco(diferenca, reg.tanque),
            recomendacao=_recomendacao_balanco(diferenca, nivel, reg.tanque),
            posto=reg.posto,
        )
        divergencias.append(div)
        logger.debug("R1 — %s %s: dif=%.1f L [%s]", reg.data, reg.tanque, diferenca, nivel)

    return divergencias


# ---------------------------------------------------------------------------
# Regra R2 — Estoque negativo
# ---------------------------------------------------------------------------

def auditar_estoque_negativo(
    registros: List[RegistroLMC],
    cfg: ConfiguracaoTolerancia = TOLERANCIAS_PADRAO,
) -> List[Divergencia]:
    """Estoque_final negativo é fisicamente impossível — sempre CRÍTICO."""
    divergencias: List[Divergencia] = []

    for reg in registros:
        if reg.estoque_final < 0:
            div = Divergencia(
                tipo=TipoDivergencia.LMC,
                data=reg.data,
                referencia=reg.tanque,
                descricao=(
                    f"Estoque NEGATIVO no {reg.tanque}: "
                    f"{reg.estoque_final:.1f} L. Valor fisicamente impossível."
                ),
                valor_esperado=0.0,
                valor_informado=round(reg.estoque_final, 2),
                diferenca=round(reg.estoque_final, 2),
                nivel_risco=NivelRisco.CRITICO,
                causa_provavel=(
                    "Lançamento incorreto de vendas superiores ao estoque disponível, "
                    "ou digitação errada no sistema."
                ),
                recomendacao=(
                    f"Corrigir imediatamente o registro do {reg.tanque}. "
                    "Identificar qual lançamento causou o saldo negativo e estornar."
                ),
                posto=reg.posto,
            )
            divergencias.append(div)

    return divergencias


# ---------------------------------------------------------------------------
# Regra R3 — Entrada sem venda
# ---------------------------------------------------------------------------

def auditar_entrada_sem_venda(
    registros: List[RegistroLMC],
    cfg: ConfiguracaoTolerancia = TOLERANCIAS_PADRAO,
) -> List[Divergencia]:
    """
    Se um tanque recebeu entrada mas registrou zero vendas no mesmo dia,
    pode indicar que as vendas daquele tanque não foram lançadas.
    """
    divergencias: List[Divergencia] = []

    for reg in registros:
        if reg.entradas > 0 and reg.vendas == 0:
            div = Divergencia(
                tipo=TipoDivergencia.LMC,
                data=reg.data,
                referencia=reg.tanque,
                descricao=(
                    f"{reg.tanque} recebeu entrada de {reg.entradas:.1f} L "
                    "mas registrou ZERO vendas no dia."
                ),
                valor_esperado=1.0,   # simbólico: esperava-se ao menos alguma venda
                valor_informado=0.0,
                diferenca=0.0,
                nivel_risco=NivelRisco.MEDIO,
                causa_provavel=(
                    "Possível falta de lançamento das vendas deste tanque no dia, "
                    "ou bomba foi mantida fora de operação (manutenção não registrada)."
                ),
                recomendacao=(
                    f"Verificar se as bombas abastecidas pelo {reg.tanque} operaram no dia. "
                    "Confirmar lançamentos de vendas nas aferições de bombas."
                ),
                posto=reg.posto,
            )
            divergencias.append(div)

    return divergencias


# ---------------------------------------------------------------------------
# Regra R4 — Variação extrema de vendas (análise de série histórica)
# ---------------------------------------------------------------------------

def auditar_variacao_vendas(
    registros: List[RegistroLMC],
    limite_variacao_pct: float = 80.0,
    minimo_historico: int = 3,
) -> List[Divergencia]:
    """
    Para cada tanque, compara as vendas do dia com a média histórica.
    Variações acima de `limite_variacao_pct`% são sinalizadas.
    Requer ao menos `minimo_historico` registros para calcular média.
    """
    divergencias: List[Divergencia] = []

    # Agrupar por tanque
    from collections import defaultdict
    por_tanque: dict[str, List[RegistroLMC]] = defaultdict(list)
    for reg in registros:
        por_tanque[reg.tanque].append(reg)

    for tanque, regs in por_tanque.items():
        if len(regs) < minimo_historico:
            continue

        vendas_serie = np.array([r.vendas for r in regs], dtype=float)
        media = np.mean(vendas_serie)

        if media == 0:
            continue

        for reg in regs:
            variacao_pct = abs((reg.vendas - media) / media) * 100
            if variacao_pct >= limite_variacao_pct:
                nivel = NivelRisco.ALTO if variacao_pct >= 120 else NivelRisco.MEDIO
                sentido = "acima" if reg.vendas > media else "abaixo"
                div = Divergencia(
                    tipo=TipoDivergencia.LMC,
                    data=reg.data,
                    referencia=tanque,
                    descricao=(
                        f"Vendas do {tanque} em {reg.data} ({reg.vendas:.1f} L) "
                        f"estão {variacao_pct:.1f}% {sentido} da média histórica ({media:.1f} L)."
                    ),
                    valor_esperado=round(media, 2),
                    valor_informado=round(reg.vendas, 2),
                    diferenca=round(reg.vendas - media, 2),
                    nivel_risco=nivel,
                    causa_provavel=(
                        f"Variação atípica de {variacao_pct:.1f}% em relação à média. "
                        "Pode indicar erro de lançamento, evento especial não registrado "
                        "ou manipulação de dados."
                    ),
                    recomendacao=(
                        f"Cruzar vendas do {tanque} com relatório de aferição de bombas "
                        "para validar o volume real vendido no dia."
                    ),
                    posto=reg.posto,
                )
                divergencias.append(div)

    return divergencias


# ---------------------------------------------------------------------------
# Ponto de entrada consolidado
# ---------------------------------------------------------------------------

def executar_auditoria_lmc(
    registros: List[RegistroLMC],
    cfg: ConfiguracaoTolerancia = TOLERANCIAS_PADRAO,
) -> List[Divergencia]:
    """Executa todas as regras LMC e retorna divergências consolidadas."""
    todas: List[Divergencia] = []
    todas.extend(auditar_balanco(registros, cfg))
    todas.extend(auditar_estoque_negativo(registros, cfg))
    todas.extend(auditar_entrada_sem_venda(registros, cfg))
    todas.extend(auditar_variacao_vendas(registros))

    logger.info(
        "Auditoria LMC concluída: %d divergências encontradas em %d registros.",
        len(todas),
        len(registros),
    )
    return todas
