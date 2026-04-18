"""
auditoria_service.py — Orquestrador central da auditoria.

Responsabilidades:
  - Receber os registros já parseados
  - Chamar as regras de cada módulo (LMC, Caixa, Aferição)
  - Consolidar divergências em um ResultadoAuditoria
  - Suportar auditoria de múltiplos postos
  - Fornecer métricas consolidadas
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import List, Optional

from app.models.schemas import (
    ConfiguracaoTolerancia,
    Divergencia,
    NivelRisco,
    RegistroAfericao,
    RegistroCaixa,
    RegistroLMC,
    ResultadoAuditoria,
    TOLERANCIAS_PADRAO,
)
from app.rules.afericao import executar_auditoria_afericao
from app.rules.caixa import executar_auditoria_caixa
from app.rules.lmc import executar_auditoria_lmc
from app.rules.perdas_sobras import executar_auditoria_perdas_sobras
from app.services.parser_service import (
    carregar_afericao,
    carregar_caixa,
    carregar_lmc,
    descobrir_arquivos,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auditoria de um único posto
# ---------------------------------------------------------------------------

class AuditoriaService:
    """
    Serviço principal de auditoria para um posto.

    Uso básico:
        service = AuditoriaService(posto="Posto Central", cfg=TOLERANCIAS_PADRAO)
        resultado = service.auditar_pasta(Path("data/entradas"))
        print(resultado.divergencias)
    """

    def __init__(
        self,
        posto: str = "Posto Não Identificado",
        cfg: ConfiguracaoTolerancia = TOLERANCIAS_PADRAO,
        limite_sangria: float = 2000.0,
    ) -> None:
        self.posto = posto
        self.cfg = cfg
        self.limite_sangria = limite_sangria

    # ------------------------------------------------------------------
    # Interface de alto nível: pasta de entrada
    # ------------------------------------------------------------------

    def auditar_pasta(self, pasta_entrada: Path) -> ResultadoAuditoria:
        """
        Descobre automaticamente os arquivos dentro de `pasta_entrada` e
        executa a auditoria completa.
        """
        logger.info("Iniciando auditoria do posto '%s' em '%s'", self.posto, pasta_entrada)

        arquivos = descobrir_arquivos(pasta_entrada)
        encontrados = {k: v for k, v in arquivos.items() if v is not None}
        ausentes = [k for k, v in arquivos.items() if v is None]

        if ausentes:
            logger.warning("Arquivos não encontrados em '%s': %s", pasta_entrada, ausentes)

        registros_lmc: List[RegistroLMC] = []
        registros_caixa: List[RegistroCaixa] = []
        registros_afericao: List[RegistroAfericao] = []

        if "lmc" in encontrados:
            registros_lmc = carregar_lmc(encontrados["lmc"], posto=self.posto)

        if "caixa" in encontrados:
            registros_caixa = carregar_caixa(encontrados["caixa"], posto=self.posto)

        if "afericao" in encontrados:
            registros_afericao = carregar_afericao(encontrados["afericao"], posto=self.posto)

        return self.auditar_registros(
            registros_lmc=registros_lmc,
            registros_caixa=registros_caixa,
            registros_afericao=registros_afericao,
        )

    # ------------------------------------------------------------------
    # Interface de baixo nível: registros já carregados
    # ------------------------------------------------------------------

    def auditar_registros(
        self,
        registros_lmc: List[RegistroLMC] | None = None,
        registros_caixa: List[RegistroCaixa] | None = None,
        registros_afericao: List[RegistroAfericao] | None = None,
    ) -> ResultadoAuditoria:
        """
        Executa todas as regras sobre os registros fornecidos e retorna
        um ResultadoAuditoria consolidado.
        """
        resultado = ResultadoAuditoria(
            posto=self.posto,
            data_auditoria=date.today(),
        )

        # --- LMC ---
        if registros_lmc:
            divs_lmc = executar_auditoria_lmc(registros_lmc, self.cfg)
            for div in divs_lmc:
                resultado.adicionar_divergencia(div)
            logger.info("LMC: %d divergências", len(divs_lmc))

            # --- Perdas e Sobras (extensão do LMC) ---
            divs_ps = executar_auditoria_perdas_sobras(registros_lmc, self.cfg)
            for div in divs_ps:
                resultado.adicionar_divergencia(div)
            if divs_ps:
                logger.info("PERDAS/SOBRAS: %d divergências", len(divs_ps))
        else:
            logger.warning("Nenhum registro LMC fornecido para auditoria.")

        # --- Caixa ---
        if registros_caixa:
            divs_caixa = executar_auditoria_caixa(registros_caixa, self.cfg, self.limite_sangria)
            for div in divs_caixa:
                resultado.adicionar_divergencia(div)
            logger.info("CAIXA: %d divergências", len(divs_caixa))
        else:
            logger.warning("Nenhum registro de caixa fornecido para auditoria.")

        # --- Aferição ---
        if registros_afericao:
            divs_afericao = executar_auditoria_afericao(registros_afericao, self.cfg)
            for div in divs_afericao:
                resultado.adicionar_divergencia(div)
            logger.info("AFERIÇÃO: %d divergências", len(divs_afericao))
        else:
            logger.warning("Nenhum registro de aferição fornecido para auditoria.")

        # Calcular métricas de score e contagens
        resultado.calcular_metricas()

        logger.info(
            "Auditoria do posto '%s' concluída: %d divergências | score %.1f%%",
            self.posto,
            resultado.total_divergencias,
            resultado.score_conformidade,
        )

        return resultado

    # ------------------------------------------------------------------
    # Filtros utilitários
    # ------------------------------------------------------------------

    @staticmethod
    def filtrar_por_risco(
        resultado: ResultadoAuditoria,
        nivel_minimo: NivelRisco,
    ) -> List[Divergencia]:
        """Retorna apenas as divergências com risco >= nivel_minimo."""
        ordem = [NivelRisco.BAIXO, NivelRisco.MEDIO, NivelRisco.ALTO, NivelRisco.CRITICO]
        idx_minimo = ordem.index(nivel_minimo)
        return [
            d for d in resultado.divergencias
            if ordem.index(d.nivel_risco) >= idx_minimo
        ]

    @staticmethod
    def divergencias_por_tipo(
        resultado: ResultadoAuditoria,
    ) -> dict[str, List[Divergencia]]:
        """Agrupa divergências por tipo (LMC, CAIXA, AFERIÇÃO)."""
        grupos: dict[str, List[Divergencia]] = {}
        for div in resultado.divergencias:
            grupos.setdefault(div.tipo.value, []).append(div)
        return grupos


# ---------------------------------------------------------------------------
# Auditoria de múltiplos postos
# ---------------------------------------------------------------------------

class AuditoriaMultiPostoService:
    """
    Coordena a auditoria de múltiplos postos, cada um com sua própria
    subpasta de dados.

    Estrutura esperada em `pasta_raiz`:
        pasta_raiz/
            posto_central/
                lmc.xlsx
                caixa.csv
                afericao.xlsx
            posto_norte/
                ...
    """

    def __init__(
        self,
        cfg: ConfiguracaoTolerancia = TOLERANCIAS_PADRAO,
        limite_sangria: float = 2000.0,
    ) -> None:
        self.cfg = cfg
        self.limite_sangria = limite_sangria

    def auditar_todos(self, pasta_raiz: Path) -> List[ResultadoAuditoria]:
        """
        Itera sobre subpastas de `pasta_raiz`, executa auditoria em cada uma
        e retorna lista de resultados.
        """
        resultados: List[ResultadoAuditoria] = []

        subpastas = sorted(p for p in pasta_raiz.iterdir() if p.is_dir())
        if not subpastas:
            logger.warning("Nenhuma subpasta encontrada em '%s'.", pasta_raiz)
            return resultados

        for subpasta in subpastas:
            nome_posto = subpasta.name.replace("_", " ").title()
            service = AuditoriaService(
                posto=nome_posto,
                cfg=self.cfg,
                limite_sangria=self.limite_sangria,
            )
            try:
                resultado = service.auditar_pasta(subpasta)
                resultados.append(resultado)
            except Exception as exc:
                logger.error("Falha ao auditar posto '%s': %s", nome_posto, exc, exc_info=True)

        logger.info(
            "Auditoria multi-posto concluída: %d postos auditados.", len(resultados)
        )
        return resultados

    @staticmethod
    def ranking_conformidade(resultados: List[ResultadoAuditoria]) -> List[ResultadoAuditoria]:
        """Retorna postos ordenados do menor score (pior) ao maior (melhor)."""
        return sorted(resultados, key=lambda r: r.score_conformidade)
