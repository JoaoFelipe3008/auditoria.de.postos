"""
xlsx_caixa_parser.py — Parser para o relatório "Prestação de Contas Sintético"
exportado pelo Quality Automação (e sistemas similares) em formato .xlsx.

Estrutura esperada do arquivo:
  Linha 0  : "Caixa"
  Linha 1  : cabeçalho colunas de pagamento
             (Meios de Pagamento | Apresentado (R$) | Sangria (R$) | Apurado (R$) | Diferença (R$))
  Linhas 2+: meios de pagamento individuais (Dinheiro, Notas, Cartão, ...)
  Linha "Total": totais consolidados do dia
  Linha "Funcionário" (cabeçalho): Total Apresentado (R$) | Total Apurado (R$) | Diferença Total (R$)
  Linhas abaixo: um operador por linha → PRINCIPAL FONTE DE DADOS
  Linha "Total": total dos operadores

Lógica de mapeamento para RegistroCaixa (um registro por operador):
  - operador       → nome do funcionário
  - data           → data da criação do arquivo (metadados openpyxl) ou mtime
  - total_informado→ Total Apresentado do operador
  - pix            → Total Apurado do operador (calibrado para que a fórmula
                     dinheiro + cartao + pix − sangria = Apurado exatamente)
  - dinheiro, cartao, sangria → 0 (não disponível individualmente por operador)

Dessa forma, divergencia = total_informado − pix = Apresentado − Apurado,
que é exatamente a diferença individual do operador.
"""

from __future__ import annotations

import logging
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

from app.models.schemas import RegistroCaixa

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------

def _norm(texto: str) -> str:
    """Normaliza para comparação: lowercase, sem acentos."""
    t = unicodedata.normalize("NFD", str(texto).strip().lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def _float(valor) -> float:
    if pd.isna(valor):
        return 0.0
    try:
        return float(str(valor).replace(",", ".").strip())
    except (ValueError, TypeError):
        return 0.0


def _data_do_arquivo(caminho: Path) -> date:
    """
    Tenta obter a data do relatório dos metadados openpyxl.
    Fallback: data de modificação do arquivo.
    """
    try:
        import openpyxl
        wb = openpyxl.load_workbook(str(caminho), read_only=True)
        props = wb.properties
        dt = props.created or props.modified
        wb.close()
        if dt:
            if hasattr(dt, "date"):
                return dt.date()
            return datetime.fromisoformat(str(dt)).date()
    except Exception:
        pass
    return datetime.fromtimestamp(caminho.stat().st_mtime).date()


# ---------------------------------------------------------------------------
# Detecção de formato
# ---------------------------------------------------------------------------

def e_formato_sintetico(df_raw: pd.DataFrame) -> bool:
    """
    Retorna True se o DataFrame parece ser um "Prestação de Contas Sintético".
    Critério: alguma célula nas primeiras 5 linhas contém
    'meios de pagamento', 'prestacao de contas' ou 'apresentado'.
    """
    for _, row in df_raw.head(5).iterrows():
        for val in row.values:
            t = _norm(str(val))
            if "meios de pagamento" in t or "prestacao de contas" in t or "apresentado" in t:
                return True
    return False


# ---------------------------------------------------------------------------
# Extratores
# ---------------------------------------------------------------------------

def _extrair_data_relatorio(df_raw: pd.DataFrame, caminho: Path) -> date:
    """
    Tenta encontrar uma data no conteúdo do DataFrame (formato DD/MM/YYYY).
    Fallback: metadados do arquivo.
    """
    import re
    for _, row in df_raw.head(10).iterrows():
        for val in row.values:
            m = re.search(r"(\d{2}/\d{2}/\d{4})", str(val))
            if m:
                try:
                    return datetime.strptime(m.group(1), "%d/%m/%Y").date()
                except ValueError:
                    pass
    return _data_do_arquivo(caminho)


def _extrair_operadores(df_raw: pd.DataFrame) -> List[Tuple[str, float, float]]:
    """
    Localiza a tabela de "Funcionário" e retorna lista de
    (nome_operador, total_apresentado, total_apurado).
    """
    resultado: List[Tuple[str, float, float]] = []
    em_tabela = False

    for _, row in df_raw.iterrows():
        valores_txt = [str(v).strip() for v in row.values if str(v).strip() not in ("nan", "")]

        if not valores_txt:
            continue

        # Detecta o cabeçalho da tabela de funcionários
        # Reconhece: "Funcionário | Total Apresentado (R$) | Total Apurado (R$) | ..."
        if (
            len(valores_txt) >= 3
            and "funcionario" in _norm(valores_txt[0])
            and "apresentado" in _norm(" ".join(valores_txt))
        ):
            em_tabela = True
            continue

        if not em_tabela:
            continue

        # Linha de total — encerra leitura da tabela
        if "total" in _norm(valores_txt[0]):
            break

        # Linha de operador: nome + pelo menos 3 valores numéricos
        if len(valores_txt) >= 3:
            nome = valores_txt[0]
            apres = _float(valores_txt[1])
            apurado = _float(valores_txt[2])

            # Sanidade: valores devem ser monetários (>= 0, não absurdos)
            if apres >= 0 and apurado >= 0 and apres < 1_000_000:
                resultado.append((nome, apres, apurado))

    return resultado


def _extrair_totais_pagamento(df_raw: pd.DataFrame) -> Tuple[float, float, float]:
    """
    Extrai os totais consolidados da linha "Total" da tabela de Meios de Pagamento.
    Retorna (total_apresentado, sangria_total, total_apurado).
    """
    em_pagamentos = False

    for _, row in df_raw.iterrows():
        valores_txt = [str(v).strip() for v in row.values if str(v).strip() not in ("nan", "")]

        if not valores_txt:
            continue

        # Cabeçalho de Meios de Pagamento
        if "meios de pagamento" in _norm(valores_txt[0]):
            em_pagamentos = True
            continue

        if not em_pagamentos:
            continue

        # Linha "Total" dentro de Meios de Pagamento (antes da seção Funcionário)
        if "total" in _norm(valores_txt[0]) and len(valores_txt) >= 4:
            try:
                apres   = _float(valores_txt[1])
                sangria = _float(valores_txt[2])
                apurado = _float(valores_txt[3])
                if apres > 1_000:  # sanidade
                    return (apres, sangria, apurado)
            except (IndexError, ValueError):
                pass

        # Encontrou seção de funcionários → para de buscar totais de pagamento
        if "funcionario" in _norm(valores_txt[0]):
            break

    return (0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def parsear_caixa_xlsx_sintetico(
    caminho: Path,
    posto: str = "Não informado",
) -> List[RegistroCaixa]:
    """
    Lê um relatório 'Prestação de Contas Sintético' (.xlsx) e retorna
    lista de RegistroCaixa — um por operador.

    Para cada operador:
      - total_informado = Total Apresentado (o que o operador declarou)
      - pix             = Total Apurado (calibrado para que a fórmula
                          dinheiro + cartao + pix − sangria = Apurado)
      - divergencia detectada = total_informado − pix = Apresentado − Apurado
    """
    logger.info("CAIXA XLSX Sintético: lendo '%s'", caminho.name)

    try:
        df_raw = pd.read_excel(caminho, sheet_name=0, header=None, dtype=str)
    except Exception as exc:
        raise ValueError(
            f"Não foi possível abrir o arquivo Excel '{caminho.name}': {exc}"
        ) from exc

    data_rel   = _extrair_data_relatorio(df_raw, caminho)
    operadores = _extrair_operadores(df_raw)
    totais     = _extrair_totais_pagamento(df_raw)

    if not operadores:
        raise ValueError(
            f"Relatório '{caminho.name}': nenhum operador encontrado.\n"
            "Verifique se o arquivo contém a seção 'Funcionário' com "
            "'Total Apresentado (R$)' e 'Total Apurado (R$)'."
        )

    total_apres_global, sangria_global, _ = totais

    logger.info(
        "CAIXA XLSX Sintético: %d operador(es) | data=%s | total_apres=%.2f | sangria=%.2f",
        len(operadores), data_rel, total_apres_global, sangria_global,
    )

    registros: List[RegistroCaixa] = []
    for nome, apres, apurado in operadores:
        # Calibração: pix = apurado, dinheiro=0, cartao=0, sangria=0
        # → divergencia = total_informado − pix = apres − apurado
        registros.append(RegistroCaixa(
            data=data_rel,
            operador=nome,
            dinheiro=0.0,
            cartao=0.0,
            pix=round(apurado, 2),
            sangria=0.0,
            total_informado=round(apres, 2),
            posto=posto,
        ))
        logger.debug(
            "  %s → apresentado=%.2f  apurado=%.2f  diff=%.2f",
            nome, apres, apurado, apres - apurado,
        )

    return registros
