"""
afericao.py — Regras de negócio para auditoria de aferição de bombas.

Regras aplicadas:
  R1 — Erro percentual fora da tolerância INMETRO (padrão: 0,5%)
  R2 — Erro sempre positivo (bomba sempre dando menos — prejuízo ao consumidor)
  R3 — Erro sempre negativo (bomba sempre dando mais — prejuízo ao posto)
  R4 — Bomba sem aferição no período (ausência de dados de controle)
  R5 — Variação de erro entre aferições (instabilidade mecânica)
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
    RegistroAfericao,
    TipoDivergencia,
    TOLERANCIAS_PADRAO,
)

logger = logging.getLogger(__name__)

# Tolerância legal INMETRO para bombas de combustível (Portaria INMETRO 9/2002)
TOLERANCIA_INMETRO_PCT = 0.5   # ±0,5%
TOLERANCIA_CRITICA_PCT = 1.0   # Acima disso: risco regulatório grave


# ---------------------------------------------------------------------------
# Classificação de risco por percentual de erro
# ---------------------------------------------------------------------------

def _classificar_risco_afericao(erro_pct: float, cfg: ConfiguracaoTolerancia) -> NivelRisco:
    if erro_pct <= cfg.afericao_tolerancia_baixo:
        return NivelRisco.BAIXO
    if erro_pct <= cfg.afericao_tolerancia_medio:
        return NivelRisco.MEDIO
    if erro_pct <= cfg.afericao_tolerancia_alto:
        return NivelRisco.ALTO
    return NivelRisco.CRITICO


# ---------------------------------------------------------------------------
# Regra R1 — Erro percentual fora da tolerância
# ---------------------------------------------------------------------------

def auditar_erro_tolerancia(
    registros: List[RegistroAfericao],
    cfg: ConfiguracaoTolerancia = TOLERANCIAS_PADRAO,
) -> List[Divergencia]:
    """
    Verifica se o erro percentual (|litros_medidos - litros_testados| / litros_testados)
    ultrapassa a tolerância INMETRO de 0,5%.
    """
    divergencias: List[Divergencia] = []

    for reg in registros:
        if reg.erro <= cfg.afericao_tolerancia_baixo:
            continue

        nivel = _classificar_risco_afericao(reg.erro, cfg)
        sentido = (
            "ABAIXO do esperado (prejuízo ao consumidor)"
            if reg.litros_medidos < reg.litros_testados
            else "ACIMA do esperado (prejuízo ao posto)"
        )

        # Calcular diferença absoluta em litros para contextualizar
        diff_litros = reg.litros_medidos - reg.litros_testados

        div = Divergencia(
            tipo=TipoDivergencia.AFERICAO,
            data=reg.data,
            referencia=reg.bomba,
            descricao=(
                f"Bomba {reg.bomba} com erro de aferição de {reg.erro:.3f}% "
                f"({sentido}). Testado: {reg.litros_testados:.3f} L, "
                f"Medido: {reg.litros_medidos:.3f} L (Δ {diff_litros:+.3f} L). "
                f"Tolerância INMETRO: ±{TOLERANCIA_INMETRO_PCT}%"
            ),
            valor_esperado=round(reg.litros_testados, 4),
            valor_informado=round(reg.litros_medidos, 4),
            diferenca=round(diff_litros, 4),
            nivel_risco=nivel,
            causa_provavel=(
                "Desgaste mecânico do medidor volumétrico, "
                "temperatura do combustível fora do padrão, "
                "ar na linha de abastecimento, ou adulteração do sistema de medição."
            ),
            recomendacao=(
                f"Acionar manutenção para calibração da bomba {reg.bomba} imediatamente. "
                "Se nível CRÍTICO, interditar a bomba até laudo técnico. "
                "Notificar INMETRO se o erro persiste após calibração."
            ),
            posto=reg.posto,
        )
        divergencias.append(div)
        logger.debug("R1-AFER %s %s: erro=%.3f%% [%s]", reg.data, reg.bomba, reg.erro, nivel)

    return divergencias


# ---------------------------------------------------------------------------
# Regra R2 e R3 — Direção sistemática do erro (viés)
# ---------------------------------------------------------------------------

def auditar_vies_erro(
    registros: List[RegistroAfericao],
    min_registros: int = 2,
) -> List[Divergencia]:
    """
    Se uma bomba apresenta erro sempre na mesma direção (sempre a menos ou
    sempre a mais), pode indicar adulteração intencional do medidor.
    """
    divergencias: List[Divergencia] = []

    por_bomba: dict[str, List[RegistroAfericao]] = defaultdict(list)
    for reg in registros:
        por_bomba[reg.bomba].append(reg)

    for bomba, regs in por_bomba.items():
        if len(regs) < min_registros:
            continue

        # Calcular sinal de cada erro (positivo = bomba deu a mais, negativo = a menos)
        sinais = [
            np.sign(r.litros_medidos - r.litros_testados)
            for r in regs
            if r.litros_testados != 0
        ]
        sinais_validos = [s for s in sinais if s != 0]

        if not sinais_validos or len(sinais_validos) < min_registros:
            continue

        soma_sinais = sum(sinais_validos)
        todos_mesma_direcao = abs(soma_sinais) == len(sinais_validos)

        if not todos_mesma_direcao:
            continue

        direcao = "a MENOS" if soma_sinais < 0 else "a MAIS"
        prejudicado = "consumidor (recebe menos combustível)" if soma_sinais < 0 else "posto (perde combustível)"
        nivel = NivelRisco.ALTO if len(sinais_validos) >= 3 else NivelRisco.MEDIO

        erros_medios = np.mean([r.erro for r in regs])
        datas = ", ".join(str(r.data) for r in regs)

        div = Divergencia(
            tipo=TipoDivergencia.AFERICAO,
            data=regs[-1].data,
            referencia=bomba,
            descricao=(
                f"Bomba {bomba} apresenta erro sistemático SEMPRE {direcao} "
                f"em {len(regs)} aferições ({datas}). "
                f"Erro médio: {erros_medios:.3f}%. Prejudica o {prejudicado}."
            ),
            valor_esperado=0.0,
            valor_informado=round(erros_medios, 4),
            diferenca=round(erros_medios, 4),
            nivel_risco=nivel,
            causa_provavel=(
                "Padrão de erro unidirecional sugere possível adulteração do computador "
                "de bordo da bomba (chip de faturamento), desgaste assimétrico ou "
                "calibração deliberadamente incorreta."
            ),
            recomendacao=(
                f"Solicitar perícia técnica independente na bomba {bomba}. "
                "Verificar lacres do medidor e histórico de manutenções. "
                "Considerar denúncia ao INMETRO se adulteração for confirmada."
            ),
            posto=regs[-1].posto,
        )
        divergencias.append(div)

    return divergencias


# ---------------------------------------------------------------------------
# Regra R4 — Instabilidade: alta variação entre aferições
# ---------------------------------------------------------------------------

def auditar_instabilidade(
    registros: List[RegistroAfericao],
    desvio_limite: float = 0.3,
    min_registros: int = 3,
) -> List[Divergencia]:
    """
    Alta variação de erro entre aferições indica instabilidade mecânica —
    a bomba mede ora a mais, ora a menos, de forma imprevisível.
    """
    divergencias: List[Divergencia] = []

    por_bomba: dict[str, List[RegistroAfericao]] = defaultdict(list)
    for reg in registros:
        por_bomba[reg.bomba].append(reg)

    for bomba, regs in por_bomba.items():
        if len(regs) < min_registros:
            continue

        erros = np.array([r.erro for r in regs])
        desvio = float(np.std(erros))

        if desvio < desvio_limite:
            continue

        nivel = NivelRisco.ALTO if desvio > desvio_limite * 2 else NivelRisco.MEDIO

        div = Divergencia(
            tipo=TipoDivergencia.AFERICAO,
            data=regs[-1].data,
            referencia=bomba,
            descricao=(
                f"Bomba {bomba} apresenta instabilidade nas aferições: "
                f"desvio padrão do erro = {desvio:.3f}% "
                f"(limite: {desvio_limite}%). "
                f"Erros registrados: {[round(e, 3) for e in erros.tolist()]}."
            ),
            valor_esperado=desvio_limite,
            valor_informado=round(desvio, 4),
            diferenca=round(desvio - desvio_limite, 4),
            nivel_risco=nivel,
            causa_provavel=(
                "Instabilidade mecânica no medidor volumétrico: "
                "possível desgaste de pistão ou válvula, contaminação do combustível "
                "com água ou ar, ou problema no sensor de temperatura."
            ),
            recomendacao=(
                f"Realizar manutenção preventiva completa na bomba {bomba}. "
                "Aumentar frequência de aferições até estabilização. "
                "Avaliar substituição do medidor se instabilidade persistir."
            ),
            posto=regs[-1].posto,
        )
        divergencias.append(div)

    return divergencias


# ---------------------------------------------------------------------------
# Ponto de entrada consolidado
# ---------------------------------------------------------------------------

def executar_auditoria_afericao(
    registros: List[RegistroAfericao],
    cfg: ConfiguracaoTolerancia = TOLERANCIAS_PADRAO,
) -> List[Divergencia]:
    """Executa todas as regras de aferição e retorna divergências consolidadas."""
    todas: List[Divergencia] = []
    todas.extend(auditar_erro_tolerancia(registros, cfg))
    todas.extend(auditar_vies_erro(registros))
    todas.extend(auditar_instabilidade(registros))

    logger.info(
        "Auditoria AFERIÇÃO concluída: %d divergências encontradas em %d registros.",
        len(todas),
        len(registros),
    )
    return todas
