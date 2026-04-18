"""
schemas.py — Modelos de dados e tipos do sistema de auditoria.

Centraliza todas as definições de tipos e estruturas usadas ao longo
do projeto, garantindo consistência e facilidade de manutenção.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import List, Optional


# ---------------------------------------------------------------------------
# Enumerações
# ---------------------------------------------------------------------------

class NivelRisco(str, Enum):
    BAIXO = "BAIXO"
    MEDIO = "MÉDIO"
    ALTO = "ALTO"
    CRITICO = "CRÍTICO"


class TipoDivergencia(str, Enum):
    LMC = "LMC"
    CAIXA = "CAIXA"
    AFERICAO = "AFERIÇÃO"
    PERDA_SOBRA = "PERDA/SOBRA"


# ---------------------------------------------------------------------------
# Registros de entrada (linha a linha dos arquivos)
# ---------------------------------------------------------------------------

@dataclass
class RegistroLMC:
    data: date
    tanque: str
    estoque_inicial: float
    entradas: float
    vendas: float
    estoque_final: float
    posto: str = "Não informado"
    # Campos opcionais — presentes quando o arquivo contém colunas de perdas e sobras
    perdas_sobras: float = 0.0       # diferença em litros (escritural - medidor)
    perdas_sobras_pct: float = 0.0   # diferença em percentual
    diferenca_l: float = 0.0         # diferença entre estoque medidor e escritural


@dataclass
class RegistroCaixa:
    data: date
    operador: str
    dinheiro: float
    cartao: float
    pix: float
    sangria: float
    total_informado: float
    posto: str = "Não informado"


@dataclass
class RegistroAfericao:
    data: date
    bomba: str
    litros_testados: float
    litros_medidos: float
    erro: float          # percentual já calculado na fonte, ou recalculado
    posto: str = "Não informado"


# ---------------------------------------------------------------------------
# Resultado de divergência individual
# ---------------------------------------------------------------------------

@dataclass
class Divergencia:
    tipo: TipoDivergencia
    data: date
    referencia: str          # tanque / operador / bomba
    descricao: str
    valor_esperado: float
    valor_informado: float
    diferenca: float
    nivel_risco: NivelRisco
    causa_provavel: str
    recomendacao: str
    posto: str = "Não informado"

    # Campo calculado — preenchido automaticamente
    diferenca_absoluta: float = field(init=False)

    def __post_init__(self) -> None:
        self.diferenca_absoluta = abs(self.diferenca)


# ---------------------------------------------------------------------------
# Resultado consolidado de auditoria
# ---------------------------------------------------------------------------

@dataclass
class ResultadoAuditoria:
    posto: str
    data_auditoria: date
    divergencias: List[Divergencia] = field(default_factory=list)

    # Métricas de resumo (calculadas pelo serviço de relatório)
    total_divergencias: int = 0
    divergencias_alto_risco: int = 0
    divergencias_criticas: int = 0
    score_conformidade: float = 100.0   # 0–100, quanto maior melhor

    def adicionar_divergencia(self, div: Divergencia) -> None:
        self.divergencias.append(div)

    def calcular_metricas(self) -> None:
        self.total_divergencias = len(self.divergencias)
        self.divergencias_alto_risco = sum(
            1 for d in self.divergencias if d.nivel_risco == NivelRisco.ALTO
        )
        self.divergencias_criticas = sum(
            1 for d in self.divergencias if d.nivel_risco == NivelRisco.CRITICO
        )
        # Score simples: desconta pontos por risco
        penalidade = (
            self.divergencias_criticas * 20
            + self.divergencias_alto_risco * 10
            + sum(
                5 for d in self.divergencias if d.nivel_risco == NivelRisco.MEDIO
            )
            + sum(
                2 for d in self.divergencias if d.nivel_risco == NivelRisco.BAIXO
            )
        )
        self.score_conformidade = max(0.0, 100.0 - penalidade)


# ---------------------------------------------------------------------------
# Configurações de tolerância (centralizadas e sobrescritíveis)
# ---------------------------------------------------------------------------

@dataclass
class ConfiguracaoTolerancia:
    # LMC — em litros
    lmc_tolerancia_baixo: float = 30.0
    lmc_tolerancia_medio: float = 100.0
    lmc_tolerancia_alto: float = 300.0

    # Caixa — em R$
    caixa_tolerancia_baixo: float = 10.0
    caixa_tolerancia_medio: float = 100.0
    caixa_tolerancia_alto: float = 500.0

    # Aferição — em % de erro
    afericao_tolerancia_baixo: float = 0.3
    afericao_tolerancia_medio: float = 0.5
    afericao_tolerancia_alto: float = 1.0

    # Perdas e Sobras — limiares em % (os valores no arquivo já estão em %, ex: 0.5 = 0,5%)
    perdas_pct_medio: float = 0.5    # acima disto = MÉDIO (padrão recorrente)
    perdas_pct_alto: float = 1.0     # acima disto = ALTO (alerta individual)
    perdas_pct_critico: float = 2.0  # acima disto = CRÍTICO
    perdas_litros_ruido: float = 2.0 # abaixo disto = ruído, ignorar
    perdas_fator_pico: float = 3.0   # N × média do produto = pico anormal
    perdas_dias_consecutivos: int = 3 # dias seguidos com perda = risco operacional
    perdas_pct_recorrencia: float = 0.40  # fracção de dias c/ perda para padrão recorrente


# Instância padrão usada por todo o sistema (pode ser substituída por env/config)
TOLERANCIAS_PADRAO = ConfiguracaoTolerancia()
