"""
caixa.py — Regras de negócio para auditoria do fechamento de caixa.

Regras aplicadas:
  R1 — Diferença no total: total_calculado vs total_informado
  R2 — Sangria excessiva: sangria acima de limite configurable (risco de desvio)
  R3 — Caixa zerado: todos os meios de pagamento zerados (turno fantasma?)
  R4 — Concentração de forma de pagamento: 100% em dinheiro (dificulta rastreabilidade)
  R5 — Sequência de caixas: operador com diferença recorrente (padrão suspeito)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import List

import numpy as np

from app.models.schemas import (
    ConfiguracaoTolerancia,
    Divergencia,
    NivelRisco,
    RegistroCaixa,
    TipoDivergencia,
    TOLERANCIAS_PADRAO,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Classificação de risco por magnitude da diferença monetária
# ---------------------------------------------------------------------------

def _classificar_risco_caixa(diferenca_abs: float, cfg: ConfiguracaoTolerancia) -> NivelRisco:
    if diferenca_abs <= cfg.caixa_tolerancia_baixo:
        return NivelRisco.BAIXO
    if diferenca_abs <= cfg.caixa_tolerancia_medio:
        return NivelRisco.MEDIO
    if diferenca_abs <= cfg.caixa_tolerancia_alto:
        return NivelRisco.ALTO
    return NivelRisco.CRITICO


# ---------------------------------------------------------------------------
# Regra R1 — Diferença entre total calculado e informado
# ---------------------------------------------------------------------------

def auditar_diferenca_total(
    registros: List[RegistroCaixa],
    cfg: ConfiguracaoTolerancia = TOLERANCIAS_PADRAO,
) -> List[Divergencia]:
    """
    total_calculado = dinheiro + cartao + pix - sangria
    Diferenças abaixo de R$ 0,50 são ignoradas (arredondamento de centavos).
    """
    MARGEM_CENTAVOS = 0.50
    divergencias: List[Divergencia] = []

    for reg in registros:
        calculado = reg.dinheiro + reg.cartao + reg.pix - reg.sangria
        diferenca = calculado - reg.total_informado

        if abs(diferenca) <= MARGEM_CENTAVOS:
            continue

        nivel = _classificar_risco_caixa(abs(diferenca), cfg)
        sentido = "a MAIOR" if diferenca > 0 else "a MENOR"

        div = Divergencia(
            tipo=TipoDivergencia.CAIXA,
            data=reg.data,
            referencia=reg.operador,
            descricao=(
                f"Diferença no caixa do operador {reg.operador}: "
                f"calculado R$ {calculado:.2f}, informado R$ {reg.total_informado:.2f} "
                f"(diferença de R$ {diferenca:+.2f} — {sentido})"
            ),
            valor_esperado=round(calculado, 2),
            valor_informado=round(reg.total_informado, 2),
            diferenca=round(diferenca, 2),
            nivel_risco=nivel,
            causa_provavel=(
                "Erro de fechamento manual, omissão de algum meio de pagamento, "
                "sangria não registrada ou possível adulteração do total informado."
                if diferenca < 0 else
                "Total informado a menor que o calculado. Possível tentativa de "
                "encobrir excesso de caixa ou erro de digitação."
            ),
            recomendacao=(
                f"Solicitar ao operador {reg.operador} a conferência do fechamento do turno. "
                "Verificar comprovantes de cartão e PIX e reconciliar com o sistema."
            ),
            posto=reg.posto,
        )
        divergencias.append(div)
        logger.debug("R1-CAIXA %s %s: dif=R$%.2f [%s]", reg.data, reg.operador, diferenca, nivel)

    return divergencias


# ---------------------------------------------------------------------------
# Regra R2 — Sangria excessiva
# ---------------------------------------------------------------------------

def auditar_sangria_excessiva(
    registros: List[RegistroCaixa],
    limite_sangria: float = 2000.0,
) -> List[Divergencia]:
    """
    Sangrias acima de `limite_sangria` são sinalizadas para validação.
    Sangrias acima de 3× o limite são CRÍTICAS.
    """
    divergencias: List[Divergencia] = []

    for reg in registros:
        if reg.sangria <= limite_sangria:
            continue

        nivel = NivelRisco.CRITICO if reg.sangria > limite_sangria * 3 else NivelRisco.ALTO

        div = Divergencia(
            tipo=TipoDivergencia.CAIXA,
            data=reg.data,
            referencia=reg.operador,
            descricao=(
                f"Sangria atípica no caixa do operador {reg.operador}: "
                f"R$ {reg.sangria:.2f} (limite configurado: R$ {limite_sangria:.2f})"
            ),
            valor_esperado=limite_sangria,
            valor_informado=round(reg.sangria, 2),
            diferenca=round(reg.sangria - limite_sangria, 2),
            nivel_risco=nivel,
            causa_provavel=(
                "Sangria muito acima do padrão. Pode indicar movimento incomum, "
                "necessidade legítima de retirada de caixa cheio, ou desvio de valores."
            ),
            recomendacao=(
                f"Exigir autorização documentada para sangria de R$ {reg.sangria:.2f}. "
                "Verificar se existe voucher assinado por supervisor e conferir câmeras do período."
            ),
            posto=reg.posto,
        )
        divergencias.append(div)

    return divergencias


# ---------------------------------------------------------------------------
# Regra R3 — Caixa zerado (turno fantasma)
# ---------------------------------------------------------------------------

def auditar_caixa_zerado(
    registros: List[RegistroCaixa],
) -> List[Divergencia]:
    """
    Um turno com dinheiro=0, cartao=0, pix=0 e total_informado=0
    pode indicar que o caixa nunca foi aberto ou foi deletado.
    """
    divergencias: List[Divergencia] = []

    for reg in registros:
        total_bruto = reg.dinheiro + reg.cartao + reg.pix
        if total_bruto == 0 and reg.total_informado == 0:
            div = Divergencia(
                tipo=TipoDivergencia.CAIXA,
                data=reg.data,
                referencia=reg.operador,
                descricao=(
                    f"Caixa ZERADO para operador {reg.operador} em {reg.data}: "
                    "todos os meios de pagamento e total informado são R$ 0,00."
                ),
                valor_esperado=1.0,
                valor_informado=0.0,
                diferenca=0.0,
                nivel_risco=NivelRisco.MEDIO,
                causa_provavel=(
                    "Turno registrado sem nenhum movimento financeiro. "
                    "Possível dia sem operação (feriado/manutenção) não informado, "
                    "ou registro indevido de turno."
                ),
                recomendacao=(
                    f"Confirmar se o operador {reg.operador} realmente trabalhou no dia {reg.data}. "
                    "Se sim, localizar os registros das vendas no sistema."
                ),
                posto=reg.posto,
            )
            divergencias.append(div)

    return divergencias


# ---------------------------------------------------------------------------
# Regra R4 — Concentração total em dinheiro
# ---------------------------------------------------------------------------

def auditar_concentracao_dinheiro(
    registros: List[RegistroCaixa],
    limite_pct: float = 95.0,
    valor_minimo: float = 500.0,
) -> List[Divergencia]:
    """
    Se mais de `limite_pct`% do total bruto é em dinheiro (e o total supera
    `valor_minimo`), sinaliza como suspeito pois dificulta auditoria.
    """
    divergencias: List[Divergencia] = []

    for reg in registros:
        total_bruto = reg.dinheiro + reg.cartao + reg.pix
        if total_bruto < valor_minimo or reg.dinheiro == 0:
            continue

        pct_dinheiro = (reg.dinheiro / total_bruto) * 100

        if pct_dinheiro >= limite_pct:
            div = Divergencia(
                tipo=TipoDivergencia.CAIXA,
                data=reg.data,
                referencia=reg.operador,
                descricao=(
                    f"Concentração atípica de dinheiro no caixa de {reg.operador}: "
                    f"{pct_dinheiro:.1f}% do total em espécie (R$ {reg.dinheiro:.2f} de R$ {total_bruto:.2f})"
                ),
                valor_esperado=limite_pct - 1,
                valor_informado=round(pct_dinheiro, 2),
                diferenca=round(pct_dinheiro - limite_pct, 2),
                nivel_risco=NivelRisco.MEDIO,
                causa_provavel=(
                    "Praticamente todas as vendas registradas em dinheiro, "
                    "o que é atípico para postos modernos. Pode indicar "
                    "omissão de vendas por cartão/PIX ou manipulação de meios de pagamento."
                ),
                recomendacao=(
                    "Cruzar com relatório de TEF (terminal de cartão) e extrato de PIX "
                    f"para validar se realmente não houve transações eletrônicas no turno de {reg.operador}."
                ),
                posto=reg.posto,
            )
            divergencias.append(div)

    return divergencias


# ---------------------------------------------------------------------------
# Regra R5 — Operador com diferença recorrente
# ---------------------------------------------------------------------------

def auditar_padrao_recorrente(
    registros: List[RegistroCaixa],
    cfg: ConfiguracaoTolerancia = TOLERANCIAS_PADRAO,
    min_ocorrencias: int = 2,
) -> List[Divergencia]:
    """
    Se o mesmo operador apresenta diferença de caixa em múltiplos dias,
    o padrão é suspeito e merece atenção especial.
    """
    divergencias: List[Divergencia] = []

    # Calcular diferença por registro
    por_operador: dict[str, list[float]] = defaultdict(list)
    por_operador_regs: dict[str, list[RegistroCaixa]] = defaultdict(list)

    for reg in registros:
        calculado = reg.dinheiro + reg.cartao + reg.pix - reg.sangria
        diferenca = calculado - reg.total_informado
        if abs(diferenca) > cfg.caixa_tolerancia_baixo:
            por_operador[reg.operador].append(diferenca)
            por_operador_regs[reg.operador].append(reg)

    for operador, diferencas in por_operador.items():
        if len(diferencas) < min_ocorrencias:
            continue

        total_dif = sum(abs(d) for d in diferencas)
        media_dif = total_dif / len(diferencas)
        nivel = _classificar_risco_caixa(media_dif * 1.5, cfg)  # eleva risco por recorrência

        datas_afetadas = ", ".join(str(r.data) for r in por_operador_regs[operador])

        div = Divergencia(
            tipo=TipoDivergencia.CAIXA,
            data=por_operador_regs[operador][-1].data,
            referencia=operador,
            descricao=(
                f"Operador {operador} apresentou diferença de caixa em {len(diferencas)} dias: "
                f"{datas_afetadas}. Diferença média: R$ {media_dif:.2f}."
            ),
            valor_esperado=0.0,
            valor_informado=round(media_dif, 2),
            diferenca=round(media_dif, 2),
            nivel_risco=nivel,
            causa_provavel=(
                f"Padrão recorrente de diferença de caixa para o operador {operador}. "
                "Pode indicar erro sistemático no processo de fechamento, "
                "ou retirada deliberada de valores."
            ),
            recomendacao=(
                f"Convocar operador {operador} para esclarecimentos. "
                "Avaliar treinamento de fechamento de caixa ou revisão de acesso ao sistema. "
                "Se padrão persistir, considerar auditoria formal."
            ),
            posto=por_operador_regs[operador][-1].posto,
        )
        divergencias.append(div)

    return divergencias


# ---------------------------------------------------------------------------
# Ponto de entrada consolidado
# ---------------------------------------------------------------------------

def executar_auditoria_caixa(
    registros: List[RegistroCaixa],
    cfg: ConfiguracaoTolerancia = TOLERANCIAS_PADRAO,
    limite_sangria: float = 2000.0,
) -> List[Divergencia]:
    """Executa todas as regras de caixa e retorna divergências consolidadas."""
    todas: List[Divergencia] = []
    todas.extend(auditar_diferenca_total(registros, cfg))
    todas.extend(auditar_sangria_excessiva(registros, limite_sangria))
    todas.extend(auditar_caixa_zerado(registros))
    todas.extend(auditar_concentracao_dinheiro(registros))
    todas.extend(auditar_padrao_recorrente(registros, cfg))

    logger.info(
        "Auditoria CAIXA concluída: %d divergências encontradas em %d registros.",
        len(todas),
        len(registros),
    )
    return todas
