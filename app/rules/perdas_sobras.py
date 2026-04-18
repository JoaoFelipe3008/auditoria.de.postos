"""
perdas_sobras.py — Regras de análise de Perdas e Sobras de combustível.

Regras aplicadas:
  R1 — Desvio percentual: dias com perdas/sobras acima dos limiares configurados
  R2 — Pico diário: dias com valor muito acima da média histórica do produto
  R3 — Padrão recorrente: produto com perdas frequentes no período
  R4 — Sequência consecutiva: N+ dias seguidos com perda relevante
  R5 — Divergência sistemática: diferença constante entre estoque medidor e escritural
  R6 — Produto com maior perda total no período

Política anti-spam:
  - Registros com |perdas_sobras| < perdas_litros_ruido são ignorados (noise floor)
  - Alertas individuais (R1) só para ALTO e CRÍTICO
  - Alertas de padrão (R3/R4) são um alerta por produto — não por dia
  - R6 gera no máximo um alerta por auditoria
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List, Tuple

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

# Mínimo de registros por produto para análises estatísticas
_MINIMO_HISTORICO = 5


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _tem_dados_perdas(registros: List[RegistroLMC]) -> bool:
    """Verifica se algum registro contém dados de perdas/sobras."""
    return any(
        r.perdas_sobras != 0.0 or r.perdas_sobras_pct != 0.0
        for r in registros
    )


def _agrupar_por_produto(
    registros: List[RegistroLMC],
) -> Dict[str, List[RegistroLMC]]:
    grupos: Dict[str, List[RegistroLMC]] = defaultdict(list)
    for r in registros:
        grupos[r.tanque].append(r)
    for regs in grupos.values():
        regs.sort(key=lambda r: r.data)
    return grupos


def _classificar_risco_pct(pct_abs: float, cfg: ConfiguracaoTolerancia) -> NivelRisco:
    if pct_abs >= cfg.perdas_pct_critico:
        return NivelRisco.CRITICO
    if pct_abs >= cfg.perdas_pct_alto:
        return NivelRisco.ALTO
    if pct_abs >= cfg.perdas_pct_medio:
        return NivelRisco.MEDIO
    return NivelRisco.BAIXO


def _descricao_tipo(valor_l: float) -> str:
    return "PERDA" if valor_l > 0 else "SOBRA"


def _causa_desvio(valor_l: float, pct: float, produto: str) -> str:
    tipo = _descricao_tipo(valor_l)
    if tipo == "PERDA":
        causas = [
            f"Perda de {abs(valor_l):.1f} L ({abs(pct):.3f}%) no {produto}.",
            " Causas prováveis: evaporação acima do esperado, vazamento na linha,"
            " erro de lançamento de vendas ou desvio de combustível.",
        ]
    else:
        causas = [
            f"Sobra de {abs(valor_l):.1f} L ({abs(pct):.3f}%) no {produto}.",
            " Causas prováveis: entrada de combustível não registrada,"
            " erro na medição de estoque inicial ou lançamento de vendas a menor.",
        ]
    return "".join(causas)


def _recomendacao_desvio(nivel: NivelRisco, valor_l: float, produto: str) -> str:
    tipo = _descricao_tipo(valor_l)
    base = f"Conferir lançamentos de entrada e saída do {produto} no dia."
    if nivel == NivelRisco.CRITICO:
        if tipo == "PERDA":
            return (
                base
                + " Inspecionar fisicamente o tanque e mangueiras para vazamento."
                " Acionar manutenção imediatamente. Registrar ocorrência."
            )
        return (
            base
            + " Verificar notas fiscais de entrada não registradas."
            " Confirmar medição do dipstick com segundo operador."
        )
    if nivel == NivelRisco.ALTO:
        return (
            base
            + " Validar medição do tanque (dipstick ou sensor)."
            " Cruzar com aferição de bombas do dia."
        )
    return base + " Validar medição do tanque se o padrão persistir."


# ---------------------------------------------------------------------------
# R1 — Desvio percentual diário (ALTO e CRÍTICO apenas)
# ---------------------------------------------------------------------------

def auditar_desvio_percentual(
    registros: List[RegistroLMC],
    cfg: ConfiguracaoTolerancia = TOLERANCIAS_PADRAO,
) -> List[Divergencia]:
    """
    Alerta individual para dias onde |perdas_sobras_pct| >= perdas_pct_alto.
    Dias MÉDIO (0.5–1%) são cobertos pelo padrão recorrente (R3) para evitar spam.
    """
    divergencias: List[Divergencia] = []

    for reg in registros:
        pct_abs = abs(reg.perdas_sobras_pct)
        litros_abs = abs(reg.perdas_sobras)

        # Filtro de ruído
        if litros_abs < cfg.perdas_litros_ruido:
            continue

        # Só alerta individual para ALTO/CRÍTICO — MÉDIO via padrão (R3)
        if pct_abs < cfg.perdas_pct_alto:
            continue

        nivel = _classificar_risco_pct(pct_abs, cfg)
        tipo = _descricao_tipo(reg.perdas_sobras)

        div = Divergencia(
            tipo=TipoDivergencia.PERDA_SOBRA,
            data=reg.data,
            referencia=reg.tanque,
            descricao=(
                f"{tipo} de {litros_abs:.2f} L ({pct_abs:.3f}%) no {reg.tanque} "
                f"em {reg.data.strftime('%d/%m/%Y')}. "
                f"Limite configurado: ±{cfg.perdas_pct_alto:.1f}%."
            ),
            valor_esperado=0.0,
            valor_informado=round(reg.perdas_sobras, 3),
            diferenca=round(reg.perdas_sobras, 3),
            nivel_risco=nivel,
            causa_provavel=_causa_desvio(reg.perdas_sobras, pct_abs, reg.tanque),
            recomendacao=_recomendacao_desvio(nivel, reg.perdas_sobras, reg.tanque),
            posto=reg.posto,
        )
        divergencias.append(div)
        logger.debug("R1 — %s %s: %.3f%% [%s]", reg.data, reg.tanque, pct_abs, nivel)

    return divergencias


# ---------------------------------------------------------------------------
# R2 — Pico diário (outlier vs. média do produto)
# ---------------------------------------------------------------------------

def auditar_pico_diario(
    registros: List[RegistroLMC],
    cfg: ConfiguracaoTolerancia = TOLERANCIAS_PADRAO,
) -> List[Divergencia]:
    """
    Detecta dias onde a perda/sobra em litros é N× maior que a média histórica
    do produto. Requer mínimo de registros para calcular média confiável.
    Não duplica alertas já gerados por R1.
    """
    divergencias: List[Divergencia] = []
    grupos = _agrupar_por_produto(registros)

    for produto, regs in grupos.items():
        if len(regs) < _MINIMO_HISTORICO:
            continue

        valores_abs = np.array([abs(r.perdas_sobras) for r in regs], dtype=float)
        # Filtra ruído para calcular a média real
        valores_validos = valores_abs[valores_abs >= cfg.perdas_litros_ruido]
        if len(valores_validos) < 3:
            continue

        media = float(np.mean(valores_validos))
        if media == 0:
            continue

        limiar_pico = cfg.perdas_fator_pico * media

        for reg in regs:
            litros_abs = abs(reg.perdas_sobras)
            if litros_abs < cfg.perdas_litros_ruido:
                continue

            # Já coberto por R1 como ALTO/CRÍTICO → não duplicar
            pct_abs = abs(reg.perdas_sobras_pct)
            if pct_abs >= cfg.perdas_pct_alto:
                continue

            if litros_abs >= limiar_pico:
                fator = litros_abs / media
                nivel = NivelRisco.CRITICO if fator >= cfg.perdas_fator_pico * 2 else NivelRisco.ALTO
                tipo = _descricao_tipo(reg.perdas_sobras)

                div = Divergencia(
                    tipo=TipoDivergencia.PERDA_SOBRA,
                    data=reg.data,
                    referencia=produto,
                    descricao=(
                        f"Pico de {tipo.lower()} no {produto} em "
                        f"{reg.data.strftime('%d/%m/%Y')}: {litros_abs:.1f} L "
                        f"({fator:.1f}× a média de {media:.1f} L/dia do período)."
                    ),
                    valor_esperado=round(media, 2),
                    valor_informado=round(reg.perdas_sobras, 2),
                    diferenca=round(reg.perdas_sobras, 2),
                    nivel_risco=nivel,
                    causa_provavel=(
                        f"Valor {fator:.1f}× acima da média diária do produto. "
                        "Pode indicar erro de lançamento pontual, vazamento agudo "
                        "ou medição incorreta do tanque neste dia."
                    ),
                    recomendacao=(
                        f"Verificar se houve evento operacional no {produto} em "
                        f"{reg.data.strftime('%d/%m/%Y')}: manutenção, transbordo, "
                        "troca de turno com medição dupla ou lançamento incorreto."
                    ),
                    posto=reg.posto,
                )
                divergencias.append(div)
                logger.debug("R2 — pico %s %s: %.1f L (%.1fx média)", reg.data, produto, litros_abs, fator)

    return divergencias


# ---------------------------------------------------------------------------
# R3 — Padrão recorrente por produto
# ---------------------------------------------------------------------------

def auditar_padrao_recorrente(
    registros: List[RegistroLMC],
    cfg: ConfiguracaoTolerancia = TOLERANCIAS_PADRAO,
) -> List[Divergencia]:
    """
    Um alerta por produto se ele apresenta perdas/sobras acima do limiar MÉDIO
    em proporção alta dos dias. Detecta também viés sistemático (sempre perda
    ou sempre sobra), que é mais grave que oscilação aleatória.
    """
    divergencias: List[Divergencia] = []
    grupos = _agrupar_por_produto(registros)

    for produto, regs in grupos.items():
        if len(regs) < _MINIMO_HISTORICO:
            continue

        regs_com_dados = [r for r in regs if abs(r.perdas_sobras) >= cfg.perdas_litros_ruido]
        if len(regs_com_dados) < _MINIMO_HISTORICO:
            continue

        total = len(regs_com_dados)
        acima_medio = [
            r for r in regs_com_dados
            if (abs(r.perdas_sobras_pct * 100) if abs(r.perdas_sobras_pct) < 1 else abs(r.perdas_sobras_pct)) >= cfg.perdas_pct_medio
        ]
        fracao = len(acima_medio) / total

        if fracao < cfg.perdas_pct_recorrencia:
            continue

        # Verifica viés: mesma direção em >70% dos dias
        perdas = sum(1 for r in regs_com_dados if r.perdas_sobras > 0)
        sobras = sum(1 for r in regs_com_dados if r.perdas_sobras < 0)
        direcao_dominante = max(perdas, sobras) / total
        vies = direcao_dominante >= 0.70

        total_litros = sum(r.perdas_sobras for r in regs_com_dados)
        media_dia = total_litros / total

        if vies:
            nivel = NivelRisco.ALTO
            tipo_vies = "PERDA" if perdas > sobras else "SOBRA"
            descricao_vies = (
                f"Viés sistemático de {tipo_vies.lower()} em {direcao_dominante:.0%} dos dias."
            )
            causa = (
                f"Produto {produto} apresenta {tipo_vies.lower()} sistemática: "
                f"{len(acima_medio)} de {total} dias ({fracao:.0%}) acima do limiar de "
                f"{cfg.perdas_pct_medio:.1f}%. {descricao_vies} "
                "Pode indicar problema estrutural no medidor, evaporação crônica "
                "ou lançamentos consistentemente incorretos."
            )
            recomendacao = (
                f"Auditar o processo de medição do {produto}: verificar se o sensor/dipstick "
                "está calibrado corretamente. Inspecionar vedação do tanque. "
                "Revisar o procedimento de fechamento com os operadores do turno."
            )
        else:
            nivel = NivelRisco.MEDIO
            causa = (
                f"Produto {produto} apresenta variações recorrentes: "
                f"{len(acima_medio)} de {total} dias ({fracao:.0%}) acima do limiar "
                f"de {cfg.perdas_pct_medio:.1f}%. Oscilação sem direção dominante. "
                "Pode indicar imprecisão no processo de medição ou variações operacionais."
            )
            recomendacao = (
                f"Revisar o procedimento de medição do {produto}. "
                "Verificar se diferentes operadores aplicam a mesma técnica de leitura. "
                "Considerar calibração do sensor de nível."
            )

        div = Divergencia(
            tipo=TipoDivergencia.PERDA_SOBRA,
            data=regs_com_dados[-1].data,  # data do último registro do período
            referencia=produto,
            descricao=(
                f"Padrão recorrente de perdas/sobras no {produto}: "
                f"{len(acima_medio)}/{total} dias ({fracao:.0%}) acima de "
                f"{cfg.perdas_pct_medio:.1f}%. "
                f"Total do período: {total_litros:+.1f} L (média {media_dia:+.1f} L/dia)."
            ),
            valor_esperado=0.0,
            valor_informado=round(total_litros, 2),
            diferenca=round(total_litros, 2),
            nivel_risco=nivel,
            causa_provavel=causa,
            recomendacao=recomendacao,
            posto=regs[0].posto,
        )
        divergencias.append(div)
        logger.debug("R3 — padrão %s: %d/%d dias [%s]", produto, len(acima_medio), total, nivel)

    return divergencias


# ---------------------------------------------------------------------------
# R4 — Sequência consecutiva de perdas
# ---------------------------------------------------------------------------

def auditar_sequencia_consecutiva(
    registros: List[RegistroLMC],
    cfg: ConfiguracaoTolerancia = TOLERANCIAS_PADRAO,
) -> List[Divergencia]:
    """
    Detecta sequências de N+ dias consecutivos com perda relevante.
    Emite um alerta por sequência encontrada (não por dia).
    """
    divergencias: List[Divergencia] = []
    grupos = _agrupar_por_produto(registros)
    n_min = cfg.perdas_dias_consecutivos

    for produto, regs in grupos.items():
        if len(regs) < n_min:
            continue

        # Constrói lista de dias com perda relevante
        dias_com_perda: List[Tuple[date, float]] = [
            (r.data, r.perdas_sobras)
            for r in regs
            if r.perdas_sobras > cfg.perdas_litros_ruido  # só perdas (positivo = perda)
        ]

        if len(dias_com_perda) < n_min:
            continue

        # Detecta sequências de dias consecutivos (datas seguidas)
        sequencias: List[List[Tuple[date, float]]] = []
        seq_atual: List[Tuple[date, float]] = [dias_com_perda[0]]

        for i in range(1, len(dias_com_perda)):
            data_ant = dias_com_perda[i - 1][0]
            data_cur = dias_com_perda[i][0]
            if (data_cur - data_ant).days == 1:
                seq_atual.append(dias_com_perda[i])
            else:
                if len(seq_atual) >= n_min:
                    sequencias.append(seq_atual)
                seq_atual = [dias_com_perda[i]]
        if len(seq_atual) >= n_min:
            sequencias.append(seq_atual)

        for seq in sequencias:
            n_dias = len(seq)
            total_seq = sum(v for _, v in seq)
            data_inicio = seq[0][0]
            data_fim = seq[-1][0]
            nivel = NivelRisco.ALTO if n_dias >= n_min * 2 else NivelRisco.MEDIO

            div = Divergencia(
                tipo=TipoDivergencia.PERDA_SOBRA,
                data=data_fim,
                referencia=produto,
                descricao=(
                    f"Sequência de {n_dias} dias consecutivos com perda no {produto}: "
                    f"{data_inicio.strftime('%d/%m')} a {data_fim.strftime('%d/%m/%Y')}. "
                    f"Total acumulado: {total_seq:.1f} L."
                ),
                valor_esperado=0.0,
                valor_informado=round(total_seq, 2),
                diferenca=round(total_seq, 2),
                nivel_risco=nivel,
                causa_provavel=(
                    f"Perda contínua por {n_dias} dias seguidos no {produto}. "
                    "Pode indicar vazamento lento em progressão, problema de vedação "
                    "ou erro sistemático no processo de fechamento do período."
                ),
                recomendacao=(
                    f"Inspecionar fisicamente o tanque de {produto} e toda a linha de "
                    "abastecimento. Verificar registros de manutenção do período "
                    f"{data_inicio.strftime('%d/%m')} a {data_fim.strftime('%d/%m')}. "
                    "Se a perda persiste, acionar medição volumétrica certificada."
                ),
                posto=regs[0].posto,
            )
            divergencias.append(div)
            logger.debug("R4 — sequência %s: %d dias [%s]", produto, n_dias, nivel)

    return divergencias


# ---------------------------------------------------------------------------
# R5 — Divergência sistemática entre estoques (diferenca_l)
# ---------------------------------------------------------------------------

def auditar_divergencia_estoques(
    registros: List[RegistroLMC],
    cfg: ConfiguracaoTolerancia = TOLERANCIAS_PADRAO,
) -> List[Divergencia]:
    """
    Analisa a coluna diferenca_l (Estoque Medidor − Escritural).
    Se a diferença for consistentemente grande e na mesma direção,
    indica problema de medição ou lançamento sistemático.
    """
    LIMIAR_LITROS = 10.0  # abaixo disto não é sistemático
    FRACAO_DIRECAO = 0.70  # >70% na mesma direção = sistemático

    divergencias: List[Divergencia] = []
    grupos = _agrupar_por_produto(registros)

    for produto, regs in grupos.items():
        regs_com_dif = [r for r in regs if abs(r.diferenca_l) >= LIMIAR_LITROS]
        if len(regs_com_dif) < _MINIMO_HISTORICO:
            continue

        total = len(regs_com_dif)
        positivos = sum(1 for r in regs_com_dif if r.diferenca_l > 0)
        negativos = total - positivos
        direcao_dominante = max(positivos, negativos) / total

        media_abs = float(np.mean([abs(r.diferenca_l) for r in regs_com_dif]))

        if direcao_dominante < FRACAO_DIRECAO:
            continue  # oscilação aleatória, não sistemático

        sentido = "MAIOR" if positivos > negativos else "MENOR"
        nivel = NivelRisco.ALTO if media_abs >= 50 else NivelRisco.MEDIO

        div = Divergencia(
            tipo=TipoDivergencia.PERDA_SOBRA,
            data=regs[-1].data,
            referencia=produto,
            descricao=(
                f"Divergência sistemática entre estoque medidor e escritural no {produto}: "
                f"medidor consistentemente {sentido} em {direcao_dominante:.0%} dos dias "
                f"(média de {media_abs:.1f} L de diferença em {total} registros)."
            ),
            valor_esperado=0.0,
            valor_informado=round(media_abs, 2),
            diferenca=round(media_abs, 2),
            nivel_risco=nivel,
            causa_provavel=(
                f"Estoque medidor {sentido.lower()} que o escritural de forma sistemática. "
                "Possíveis causas: sensor de nível descalibrado, diferença de temperatura "
                "afetando a leitura volumétrica, ou metodologia de medição inconsistente "
                "entre os turnos."
            ),
            recomendacao=(
                f"Solicitar calibração do sensor de nível do {produto}. "
                "Verificar se a medição por dipstick e por sensor seguem o mesmo protocolo. "
                "Comparar com medição certificada por empresa especializada."
            ),
            posto=regs[0].posto,
        )
        divergencias.append(div)
        logger.debug("R5 — divergência sistemática %s: média %.1f L [%s]", produto, media_abs, nivel)

    return divergencias


# ---------------------------------------------------------------------------
# R6 — Produto com maior perda total no período
# ---------------------------------------------------------------------------

def auditar_produto_maior_perda(
    registros: List[RegistroLMC],
    cfg: ConfiguracaoTolerancia = TOLERANCIAS_PADRAO,
) -> List[Divergencia]:
    """
    Identifica o produto com maior perda total no período e gera um único
    alerta consolidado se o total for relevante.
    Emite no máximo um alerta por auditoria.
    """
    LIMIAR_TOTAL = 20.0  # litros — abaixo não vale alertar

    grupos = _agrupar_por_produto(registros)
    totais: Dict[str, Tuple[float, float, str]] = {}  # produto → (total_l, media_l, posto)

    for produto, regs in grupos.items():
        regs_com_dados = [r for r in regs if abs(r.perdas_sobras) >= cfg.perdas_litros_ruido]
        if len(regs_com_dados) < _MINIMO_HISTORICO:
            continue
        total = sum(r.perdas_sobras for r in regs_com_dados)
        media = total / len(regs_com_dados)
        totais[produto] = (total, media, regs[0].posto)

    if not totais:
        return []

    # Só considera produtos com perda líquida positiva (perdas > sobras)
    com_perda = {p: v for p, v in totais.items() if v[0] > LIMIAR_TOTAL}
    if not com_perda:
        return []

    pior_produto = max(com_perda, key=lambda p: com_perda[p][0])
    total_l, media_l, posto = com_perda[pior_produto]

    # Risco baseado no total
    if total_l >= 200:
        nivel = NivelRisco.CRITICO
    elif total_l >= 100:
        nivel = NivelRisco.ALTO
    else:
        nivel = NivelRisco.MEDIO

    todos_produtos = sorted(
        [(p, v[0]) for p, v in totais.items()],
        key=lambda x: x[1],
        reverse=True,
    )
    ranking = " | ".join(f"{p}: {v:+.1f} L" for p, v in todos_produtos)

    div = Divergencia(
        tipo=TipoDivergencia.PERDA_SOBRA,
        data=registros[-1].data,
        referencia=pior_produto,
        descricao=(
            f"Produto com maior perda no período: {pior_produto} "
            f"({total_l:.1f} L total, média de {media_l:.1f} L/dia). "
            f"Ranking: {ranking}."
        ),
        valor_esperado=0.0,
        valor_informado=round(total_l, 2),
        diferenca=round(total_l, 2),
        nivel_risco=nivel,
        causa_provavel=(
            f"Acumulado de perdas no {pior_produto} ao longo do período auditado. "
            "Representa a soma de pequenas perdas diárias que, individualmente, "
            "podem parecer aceitáveis mas no conjunto indicam problema operacional."
        ),
        recomendacao=(
            f"Priorizar inspeção do tanque de {pior_produto}. "
            "Avaliar se as perdas são uniformes (problema estrutural) ou concentradas "
            "em datas específicas (evento pontual). "
            "Comparar com o histórico de meses anteriores para identificar tendência."
        ),
        posto=posto,
    )
    logger.debug("R6 — maior perda: %s %.1f L [%s]", pior_produto, total_l, nivel)
    return [div]


# ---------------------------------------------------------------------------
# Ponto de entrada consolidado
# ---------------------------------------------------------------------------

def executar_auditoria_perdas_sobras(
    registros: List[RegistroLMC],
    cfg: ConfiguracaoTolerancia = TOLERANCIAS_PADRAO,
) -> List[Divergencia]:
    """
    Executa todas as regras de perdas e sobras e retorna divergências consolidadas.
    Retorna lista vazia se os registros não contêm dados de perdas/sobras.
    """
    if not _tem_dados_perdas(registros):
        logger.info("Perdas/Sobras: nenhum dado disponível nos registros LMC — módulo ignorado.")
        return []

    todas: List[Divergencia] = []
    todas.extend(auditar_desvio_percentual(registros, cfg))
    todas.extend(auditar_pico_diario(registros, cfg))
    todas.extend(auditar_padrao_recorrente(registros, cfg))
    todas.extend(auditar_sequencia_consecutiva(registros, cfg))
    todas.extend(auditar_divergencia_estoques(registros, cfg))
    todas.extend(auditar_produto_maior_perda(registros, cfg))

    logger.info(
        "Auditoria Perdas/Sobras concluída: %d divergências em %d registros.",
        len(todas),
        len(registros),
    )
    return todas
