"""
historico_service.py — Persistência de auditorias em SQLite para análise temporal.

Armazena cada auditoria realizada e as métricas individuais (por operador e por
produto/tanque) para permitir gráficos de tendência e detecção de padrões recorrentes.

Tabelas:
  auditorias     — resumo de cada execução (score, divergências, data)
  metricas_caixa — diferença por operador por dia
  metricas_lmc   — perdas/sobras por tanque por dia
  divergencias   — registro individual de cada alerta gerado
"""

from __future__ import annotations

import sqlite3
import logging
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from app.models.schemas import (
    NivelRisco,
    RegistroCaixa,
    RegistroLMC,
    ResultadoAuditoria,
    TipoDivergencia,
)

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "historico.db"

_DDL = """
CREATE TABLE IF NOT EXISTS auditorias (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    posto           TEXT    NOT NULL,
    data_auditoria  TEXT    NOT NULL,
    score           REAL,
    total_diverg    INTEGER DEFAULT 0,
    criticas        INTEGER DEFAULT 0,
    altas           INTEGER DEFAULT 0,
    medias          INTEGER DEFAULT 0,
    baixas          INTEGER DEFAULT 0,
    criado_em       TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS metricas_caixa (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    auditoria_id INTEGER REFERENCES auditorias(id) ON DELETE CASCADE,
    posto        TEXT,
    data         TEXT,
    operador     TEXT,
    apresentado  REAL,
    diferenca    REAL
);

CREATE TABLE IF NOT EXISTS metricas_lmc (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    auditoria_id     INTEGER REFERENCES auditorias(id) ON DELETE CASCADE,
    posto            TEXT,
    data             TEXT,
    tanque           TEXT,
    perdas_sobras    REAL,
    perdas_sobras_pct REAL,
    diferenca_l      REAL
);

CREATE TABLE IF NOT EXISTS divergencias (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    auditoria_id INTEGER REFERENCES auditorias(id) ON DELETE CASCADE,
    tipo         TEXT,
    nivel_risco  TEXT,
    referencia   TEXT,
    data         TEXT,
    descricao    TEXT
);
"""


class HistoricoService:
    """Interface com o banco SQLite de histórico de auditorias."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._inicializar()

    # ------------------------------------------------------------------
    # Infraestrutura
    # ------------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _inicializar(self) -> None:
        with self._conn() as conn:
            conn.executescript(_DDL)

    # ------------------------------------------------------------------
    # Escrita
    # ------------------------------------------------------------------

    def salvar(
        self,
        resultado: ResultadoAuditoria,
        registros_caixa: List[RegistroCaixa],
        registros_lmc: List[RegistroLMC],
    ) -> int:
        """
        Persiste uma auditoria completa. Retorna o id gerado.
        Operação idempotente por posto+data: se já existe registro para o mesmo
        posto e data_auditoria, substitui (DELETE + INSERT) para evitar duplicatas
        ao re-analisar o mesmo arquivo.
        """
        data_str = resultado.data_auditoria.isoformat()

        with self._conn() as conn:
            # Remove auditoria anterior do mesmo posto+data (re-análise)
            conn.execute(
                "DELETE FROM auditorias WHERE posto = ? AND data_auditoria = ?",
                (resultado.posto, data_str),
            )

            cur = conn.execute(
                """INSERT INTO auditorias
                   (posto, data_auditoria, score, total_diverg, criticas, altas, medias, baixas)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    resultado.posto,
                    data_str,
                    resultado.score_conformidade,
                    resultado.total_divergencias,
                    resultado.divergencias_criticas,
                    resultado.divergencias_alto_risco,
                    sum(1 for d in resultado.divergencias if d.nivel_risco == NivelRisco.MEDIO),
                    sum(1 for d in resultado.divergencias if d.nivel_risco == NivelRisco.BAIXO),
                ),
            )
            aid = cur.lastrowid

            # Métricas de caixa (uma linha por operador)
            for r in registros_caixa:
                diff = r.total_informado - (r.dinheiro + r.cartao + r.pix - r.sangria)
                conn.execute(
                    """INSERT INTO metricas_caixa
                       (auditoria_id, posto, data, operador, apresentado, diferenca)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (aid, r.posto, r.data.isoformat(), r.operador,
                     r.total_informado, round(diff, 2)),
                )

            # Métricas de LMC (uma linha por tanque/dia)
            for r in registros_lmc:
                conn.execute(
                    """INSERT INTO metricas_lmc
                       (auditoria_id, posto, data, tanque,
                        perdas_sobras, perdas_sobras_pct, diferenca_l)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (aid, r.posto, r.data.isoformat(), r.tanque,
                     r.perdas_sobras, r.perdas_sobras_pct, r.diferenca_l),
                )

            # Divergências individuais
            for d in resultado.divergencias:
                conn.execute(
                    """INSERT INTO divergencias
                       (auditoria_id, tipo, nivel_risco, referencia, data, descricao)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (aid, d.tipo.value, d.nivel_risco.value,
                     d.referencia, d.data.isoformat(), d.descricao),
                )

        logger.info("Auditoria salva: id=%d  posto=%s  data=%s  score=%.0f%%",
                    aid, resultado.posto, data_str, resultado.score_conformidade)
        return aid

    # ------------------------------------------------------------------
    # Leitura — resumos
    # ------------------------------------------------------------------

    def postos(self) -> List[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT posto FROM auditorias ORDER BY posto"
            ).fetchall()
        return [r["posto"] for r in rows]

    def scores(self, posto: Optional[str] = None, limite: int = 60) -> List[dict]:
        """Score de conformidade ao longo do tempo."""
        sql = """
            SELECT data_auditoria AS data, posto, score,
                   total_diverg, criticas, altas
            FROM auditorias
            {where}
            ORDER BY data_auditoria
            LIMIT ?
        """
        where = "WHERE posto = ?" if posto else ""
        params = (posto, limite) if posto else (limite,)
        with self._conn() as conn:
            rows = conn.execute(sql.format(where=where), params).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Leitura — caixa
    # ------------------------------------------------------------------

    def caixa_por_operador(
        self, posto: Optional[str] = None, limite: int = 200
    ) -> List[dict]:
        """Diferença de caixa por operador ao longo do tempo."""
        sql = """
            SELECT m.data, m.operador, m.apresentado, m.diferenca
            FROM metricas_caixa m
            JOIN auditorias a ON a.id = m.auditoria_id
            {where}
            ORDER BY m.data, m.operador
            LIMIT ?
        """
        where = "WHERE m.posto = ?" if posto else ""
        params = (posto, limite) if posto else (limite,)
        with self._conn() as conn:
            rows = conn.execute(sql.format(where=where), params).fetchall()
        return [dict(r) for r in rows]

    def ranking_operadores(self, posto: Optional[str] = None) -> List[dict]:
        """Operadores ordenados por soma absoluta de diferenças (maior problema primeiro)."""
        sql = """
            SELECT m.operador,
                   COUNT(*)                     AS dias,
                   SUM(ABS(m.diferenca))        AS soma_abs,
                   SUM(m.diferenca)             AS soma_liquida,
                   AVG(m.diferenca)             AS media,
                   MIN(m.diferenca)             AS minimo,
                   MAX(m.diferenca)             AS maximo
            FROM metricas_caixa m
            JOIN auditorias a ON a.id = m.auditoria_id
            {where}
            GROUP BY m.operador
            ORDER BY soma_abs DESC
        """
        where = "WHERE m.posto = ?" if posto else ""
        params = (posto,) if posto else ()
        with self._conn() as conn:
            rows = conn.execute(sql.format(where=where), params).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Leitura — LMC
    # ------------------------------------------------------------------

    def lmc_por_tanque(
        self, posto: Optional[str] = None, limite: int = 300
    ) -> List[dict]:
        """Perdas/sobras por tanque ao longo do tempo."""
        sql = """
            SELECT m.data, m.tanque, m.perdas_sobras, m.perdas_sobras_pct, m.diferenca_l
            FROM metricas_lmc m
            JOIN auditorias a ON a.id = m.auditoria_id
            {where}
            ORDER BY m.data, m.tanque
            LIMIT ?
        """
        where = "WHERE m.posto = ?" if posto else ""
        params = (posto, limite) if posto else (limite,)
        with self._conn() as conn:
            rows = conn.execute(sql.format(where=where), params).fetchall()
        return [dict(r) for r in rows]

    def ranking_tanques(self, posto: Optional[str] = None) -> List[dict]:
        """Tanques ordenados por perda total acumulada."""
        sql = """
            SELECT m.tanque,
                   COUNT(*)               AS dias,
                   SUM(m.perdas_sobras)   AS perda_total,
                   AVG(m.perdas_sobras)   AS perda_media
            FROM metricas_lmc m
            JOIN auditorias a ON a.id = m.auditoria_id
            {where}
            GROUP BY m.tanque
            ORDER BY perda_total DESC
        """
        where = "WHERE m.posto = ?" if posto else ""
        params = (posto,) if posto else ()
        with self._conn() as conn:
            rows = conn.execute(sql.format(where=where), params).fetchall()
        return [dict(r) for r in rows]

    def tem_dados(self) -> bool:
        with self._conn() as conn:
            count = conn.execute("SELECT COUNT(*) FROM auditorias").fetchone()[0]
        return count > 0
