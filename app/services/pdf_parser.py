"""
pdf_parser.py — Extração de tabelas de PDFs de LMC (Perdas e Sobras).

Responsabilidades:
  - Abrir PDF com pdfplumber
  - Extrair tabelas por página
  - Detectar blocos por produto ("Produto: GASOLINA COMUM")
  - Remover linhas de subtotal, total e cabeçalhos repetidos
  - Normalizar e mapear colunas para o formato interno de LMC
  - Retornar DataFrame pronto para ser consumido por carregar_lmc()

Formato esperado:
  Relatório "Perdas e Sobras LMC" exportado de sistema de posto,
  com colunas como: Data, Folha, Abertura, Entrada, Aferição,
  Saída, Escritural, Fechamento, Perdas/Sobras, Estoque Medidor, etc.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes de classificação de linhas
# ---------------------------------------------------------------------------

_PALAVRAS_TOTAL = {
    "total", "subtotal", "sub-total", "sub total",
    "acumulado", "soma", "resumo", "consolidado",
    "media", "média",
}

_PALAVRAS_CABECALHO = {
    "data", "abertura", "entrada", "saida", "fechamento",
    "estoque", "medidor", "folha", "escritural", "afericao",
    "aferição", "perdas", "sobras",
}

_INDICADORES_SUBHEADER = {
    "l", "m3", "litros", "litro",
    "r$", "rs", "reais",
    "%",
    "dd/mm/aa", "dd/mm/aaaa", "dd/mm/yyyy", "mm/aaaa",
    "s/n", "n/a", "-",
}

# Mapeamento de colunas brutas → nomes internos (mesmo de parser_service)
_MAPA_COLUNAS: dict[str, str] = {
    "abertura":          "estoque_inicial",
    "estoque_inicial":   "estoque_inicial",
    "saldo_inicial":     "estoque_inicial",
    "entrada":           "entradas",
    "entradas":          "entradas",
    "recebimento":       "entradas",
    "nf":                "entradas",
    "saida":             "vendas",
    "saidas":            "vendas",
    "venda":             "vendas",
    "vendas":            "vendas",
    "consumo":           "vendas",
    "fechamento":        "estoque_final",
    "estoque_final":     "estoque_final",
    "saldo_final":       "estoque_final",
    "estoque_medidor":   "estoque_final",
    "medidor":           "estoque_final",
    "data":              "data",
    # ignorados
    "folha":             "_ignorar",
    "n_folha":           "_ignorar",
    "escritural":        "_ignorar",
    "afericao":          "_ignorar",
    "aferacao":          "_ignorar",
    "perdas_sobras":     "_ignorar",
    "diferenca":         "_ignorar",
    "diferenca_em_l":    "_ignorar",
    "diferenca_em_":     "_ignorar",
}


# ---------------------------------------------------------------------------
# Utilitários internos
# ---------------------------------------------------------------------------

def _norm(texto) -> str:
    """Normaliza texto: minúsculas, sem acentos, sem espaços extras."""
    if texto is None:
        return ""
    s = unicodedata.normalize("NFD", str(texto).strip().lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s


def _norm_coluna(nome: str) -> str:
    """Converte nome de coluna para snake_case sem acentos."""
    s = _norm(nome)
    s = re.sub(r"[\s\-/\\%°\(\)]+", "_", s)
    s = re.sub(r"[^\w]", "", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def _e_vazia(row: list) -> bool:
    return all(not str(c).strip() for c in row if c is not None)


def _e_total(row: list) -> bool:
    textos = [_norm(c) for c in row if c is not None and str(c).strip()]
    for t in textos:
        for palavra in _PALAVRAS_TOTAL:
            if palavra in t:
                return True
    return False


def _e_subheader(row: list) -> bool:
    celulas = [_norm(c) for c in row if c is not None and str(c).strip()]
    if not celulas:
        return False
    matches = sum(1 for c in celulas if c in _INDICADORES_SUBHEADER)
    return matches >= max(1, len(celulas) // 2)


def _e_cabecalho(row: list) -> bool:
    """Retorna True se a linha parece um cabeçalho (≥2 palavras-chave de cabeçalho)."""
    celulas = [_norm(c) for c in row if c is not None and str(c).strip()]
    acertos = sum(
        1 for c in celulas
        if any(kw in c for kw in _PALAVRAS_CABECALHO)
    )
    return acertos >= 2


def _detectar_produto(row: list) -> Optional[str]:
    """
    Detecta declaração de produto numa linha.
    Ex: "Produto: GASOLINA COMUM", "Combustível: ETANOL"
    """
    for cell in row:
        texto = _norm(cell)
        for prefixo in ("produto", "combustivel", "tanque"):
            if texto.startswith(prefixo):
                nome = re.sub(
                    rf"^{prefixo}\s*[:–\-]?\s*", "",
                    str(cell).strip(),
                    flags=re.IGNORECASE,
                )
                return nome.strip() or "Produto desconhecido"
    return None


# ---------------------------------------------------------------------------
# Extração principal
# ---------------------------------------------------------------------------

def extrair_tabelas_pdf(caminho: Path) -> Tuple[pd.DataFrame, dict]:
    """
    Extrai dados tabulares de um PDF de LMC.

    Retorna:
        df     — DataFrame com colunas internas de LMC
        info   — dict com metadados: paginas_lidas, paginas_total,
                 produtos_encontrados, linhas_extraidas, avisos

    Lança:
        ImportError  — se pdfplumber não estiver instalado
        ValueError   — se não encontrar nenhuma tabela ou dado válido
    """
    try:
        import pdfplumber  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "pdfplumber não está instalado. Execute: pip install pdfplumber"
        ) from exc

    info: dict = {
        "paginas_total": 0,
        "paginas_lidas": 0,
        "produtos_encontrados": [],
        "linhas_extraidas": 0,
        "avisos": [],
    }

    todas_as_linhas: List[dict] = []
    cabecalho_global: Optional[list] = None
    produto_atual = "Produto não identificado"

    with pdfplumber.open(str(caminho)) as pdf:
        info["paginas_total"] = len(pdf.pages)
        logger.info("PDF aberto: %d página(s) — %s", len(pdf.pages), caminho.name)

        for num_pag, pagina in enumerate(pdf.pages, start=1):
            tabelas = pagina.extract_tables()
            if not tabelas:
                logger.debug("Página %d: sem tabelas detectadas.", num_pag)
                # Tenta texto bruto como fallback para páginas sem tabela formal
                texto = pagina.extract_text() or ""
                if texto.strip():
                    info["avisos"].append(
                        f"Página {num_pag}: sem tabela formal, apenas texto. "
                        "Dados dessa página podem estar incompletos."
                    )
                continue

            info["paginas_lidas"] += 1

            for tabela in tabelas:
                if not tabela:
                    continue

                # Procura cabeçalho dentro da tabela (primeiras 5 linhas)
                cab_local: Optional[list] = None
                idx_inicio = 0

                for i, row in enumerate(tabela[:5]):
                    if _e_cabecalho(row):
                        cab_local = row
                        idx_inicio = i + 1
                        # Pula sub-header de unidades (L, %, DD/MM/AA...)
                        if idx_inicio < len(tabela) and _e_subheader(tabela[idx_inicio]):
                            idx_inicio += 1
                        break

                # Se não encontrou cabeçalho local, reutiliza global
                if cab_local is None:
                    if cabecalho_global is None:
                        info["avisos"].append(
                            f"Página {num_pag}: tabela sem cabeçalho reconhecível — ignorada."
                        )
                        continue
                    cab_local = cabecalho_global
                    idx_inicio = 0
                else:
                    cabecalho_global = cab_local

                nomes_colunas = [
                    str(c).strip() if c and str(c).strip() else f"_col{i}"
                    for i, c in enumerate(cab_local)
                ]

                for row in tabela[idx_inicio:]:
                    if _e_vazia(row):
                        continue
                    if _e_total(row):
                        logger.debug("Página %d: linha de total ignorada.", num_pag)
                        continue
                    if _e_subheader(row):
                        continue
                    if _e_cabecalho(row):
                        continue

                    prod = _detectar_produto(row)
                    if prod:
                        produto_atual = prod
                        if prod not in info["produtos_encontrados"]:
                            info["produtos_encontrados"].append(prod)
                        continue

                    # Linha de dados — associa ao cabeçalho
                    registro = {
                        col: (str(val).strip() if val is not None else "")
                        for col, val in zip(nomes_colunas, row)
                    }
                    registro["__tanque__"] = produto_atual
                    todas_as_linhas.append(registro)

    if not todas_as_linhas:
        raise ValueError(
            "Nenhuma linha de dados foi extraída do PDF. "
            "Verifique se o arquivo contém tabelas digitais (não escaneadas)."
        )

    df = pd.DataFrame(todas_as_linhas)
    info["linhas_extraidas"] = len(df)

    # --- Mapear colunas ---
    nomes_ja_usados: set[str] = set()
    cols_manter: dict[str, str] = {}

    for col in df.columns:
        if col == "__tanque__":
            cols_manter[col] = col
            continue
        interno = _MAPA_COLUNAS.get(_norm_coluna(col))
        if interno and interno != "_ignorar" and interno not in nomes_ja_usados:
            cols_manter[col] = interno
            nomes_ja_usados.add(interno)

    existentes = [c for c in cols_manter if c in df.columns]
    df = df[existentes].rename(columns=cols_manter)

    # Coluna tanque
    if "__tanque__" in df.columns:
        df["tanque"] = df["__tanque__"]
        df = df.drop(columns=["__tanque__"])

    # --- Filtro: apenas linhas com data válida ---
    if "data" in df.columns:
        def _tem_data(v) -> bool:
            try:
                pd.to_datetime(str(v).strip(), dayfirst=True)
                return True
            except Exception:
                return False

        mascara = df["data"].apply(_tem_data)
        removidas = int((~mascara).sum())
        df = df[mascara].copy()
        if removidas:
            logger.debug("%d linha(s) sem data válida removidas.", removidas)

    if df.empty:
        raise ValueError(
            "O PDF foi lido mas nenhuma linha continha data válida. "
            "Verifique o formato do arquivo."
        )

    logger.info(
        "PDF processado: %d página(s) lida(s), %d linha(s) extraída(s), "
        "%d produto(s): %s",
        info["paginas_lidas"],
        len(df),
        len(info["produtos_encontrados"]),
        info["produtos_encontrados"],
    )

    return df, info
