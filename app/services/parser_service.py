"""
parser_service.py — Leitura, validação e padronização dos arquivos de entrada.

Responsabilidades:
  - Detectar e carregar arquivos .xlsx, .xls, .csv e .pdf
  - Normalizar nomes de colunas (lowercase, sem acentos, sem espaços extras)
  - Converter tipos de dados
  - Validar colunas obrigatórias
  - Retornar listas tipadas de registros (schemas.py)

Suporta três formatos de LMC:
  - Formato MVP   : planilha simples com as 6 colunas padrão
  - Formato Real  : relatório exportado de sistema de posto (PDF→Excel),
                    com cabeçalhos múltiplos, células mescladas, blocos
                    por produto, linhas de total e colunas extras.
  - Formato PDF   : relatório "Perdas e Sobras LMC" em PDF digital,
                    processado por pdf_parser.py via pdfplumber.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from app.models.schemas import (
    RegistroAfericao,
    RegistroCaixa,
    RegistroLMC,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Utilitários de normalização
# ---------------------------------------------------------------------------

def _normalizar_coluna(nome: str) -> str:
    """Remove acentos, espaços e converte para snake_case."""
    nome = unicodedata.normalize("NFD", str(nome).strip().lower())
    nome = "".join(c for c in nome if unicodedata.category(c) != "Mn")
    nome = re.sub(r"[\s\-/\\%°]+", "_", nome)
    nome = re.sub(r"[^\w]", "", nome)
    nome = re.sub(r"_+", "_", nome).strip("_")
    return nome


def _normalizar_colunas(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [_normalizar_coluna(c) for c in df.columns]
    return df


def _validar_colunas(df: pd.DataFrame, obrigatorias: List[str], arquivo: str) -> None:
    faltando = [c for c in obrigatorias if c not in df.columns]
    if faltando:
        raise ValueError(
            f"Arquivo '{arquivo}' está faltando as colunas: {faltando}.\n"
            f"Colunas encontradas: {list(df.columns)}"
        )


def _para_float(valor) -> float:
    """
    Converte valores monetários ou numéricos para float.

    Suporta dois formatos:
      - Brasileiro: "1.234,56" ou "R$ 1.234,56" → ponto como milhar, vírgula como decimal
      - Padrão:     "1234.56" ou "20.001"        → ponto como decimal
    """
    if pd.isna(valor):
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    if isinstance(valor, str):
        valor = valor.replace("R$", "").replace("%", "").strip()
        if not valor or valor in ("-", "--", "n/a", "N/A"):
            return 0.0
        # Formato brasileiro: tem vírgula E ponto → ponto é milhar
        if "," in valor and "." in valor:
            valor = valor.replace(".", "").replace(",", ".")
        # Apenas vírgula como decimal (sem ponto) → ex: "1234,56"
        elif "," in valor and "." not in valor:
            valor = valor.replace(",", ".")
        # Apenas ponto → já é formato padrão, não mexer
    try:
        return float(valor)
    except (ValueError, TypeError):
        return 0.0


def _para_date(valor) -> date:
    """Converte string ou Timestamp para date."""
    if isinstance(valor, date) and not isinstance(valor, type(pd.NaT)):
        return valor
    if isinstance(valor, pd.Timestamp):
        return valor.date()
    s = str(valor).strip()
    # Formato ISO YYYY-MM-DD
    if len(s) >= 10 and s[4] == "-":
        return pd.to_datetime(s, format="%Y-%m-%d").date()
    # Formato brasileiro DD/MM/YYYY ou DD/MM/YY
    return pd.to_datetime(s, dayfirst=True).date()


def _carregar_arquivo(caminho: Path, header: int | None = 0) -> pd.DataFrame:
    """
    Carrega Excel, CSV ou PDF de forma transparente.

    Para PDF, delega para pdf_parser.extrair_tabelas_pdf() e retorna
    apenas o DataFrame — os metadados de extração ficam disponíveis
    via carregar_lmc() que chama _carregar_pdf_lmc() diretamente.
    """
    sufixo = caminho.suffix.lower()
    if sufixo in (".xlsx", ".xls"):
        df = pd.read_excel(caminho, dtype=str, header=header)
    elif sufixo == ".csv":
        df = pd.read_csv(caminho, dtype=str, sep=None, engine="python", header=header)
    elif sufixo == ".pdf":
        # PDF só deve chegar aqui se chamado fora do fluxo normal de LMC.
        # O fluxo principal usa _carregar_pdf_lmc() diretamente.
        from app.services.pdf_parser import extrair_tabelas_pdf  # noqa: PLC0415
        df, _ = extrair_tabelas_pdf(caminho)
    else:
        raise ValueError(f"Formato não suportado: {sufixo}")
    return df


def _carregar_pdf_lmc(caminho: Path) -> Tuple[pd.DataFrame, dict]:
    """
    Delega a leitura do PDF para pdf_parser e retorna (df, info).

    Mantém separado de _carregar_arquivo para preservar os metadados
    de extração (páginas lidas, produtos encontrados, avisos).
    """
    from app.services.pdf_parser import extrair_tabelas_pdf  # noqa: PLC0415
    return extrair_tabelas_pdf(caminho)


def _celula_texto(val) -> str:
    """Retorna o conteúdo textual de uma célula, normalizado."""
    if pd.isna(val):
        return ""
    return unicodedata.normalize("NFD", str(val).strip().lower())


# ---------------------------------------------------------------------------
# LMC — Mapeamento de colunas do formato real para o formato interno
# ---------------------------------------------------------------------------
# Cada entrada mapeia um nome normalizado (sem acento, snake_case) para
# o nome interno esperado pelas regras de negócio.

_MAPA_COLUNAS_REAL: dict[str, str] = {
    # estoque_inicial
    "abertura":                "estoque_inicial",
    "estoque_inicial":         "estoque_inicial",
    "saldo_inicial":           "estoque_inicial",
    "estoque_inicial_l":       "estoque_inicial",
    # entradas
    "entrada":                 "entradas",
    "entradas":                "entradas",
    "recebimento":             "entradas",
    "recebimentos":            "entradas",
    "nf":                      "entradas",
    # vendas / saídas
    "saida":                   "vendas",
    "saidas":                  "vendas",
    "venda":                   "vendas",
    "vendas":                  "vendas",
    "consumo":                 "vendas",
    "bomba":                   "vendas",   # em alguns sistemas "Bomba" = volume vendido pelas bombas
    # estoque_final
    "fechamento":              "estoque_final",
    "estoque_final":           "estoque_final",
    "saldo_final":             "estoque_final",
    "estoque_medidor":         "estoque_final",   # medição física do tanque
    "medidor":                 "estoque_final",
    # data
    "data":                    "data",
    # folha / referência — ignorado mas mapeado para não causar erro
    "folha":                   "_ignorar",
    "n_folha":                 "_ignorar",
    "referencia":              "_ignorar",
    # estoque_final escritural (valor calculado = saldo esperado no final do dia)
    "escritural":              "estoque_final",
    # aferição — coluna calculada, ignorar como input
    "afericao":                "_ignorar",
    "aferacao":                "_ignorar",
    # perdas e sobras — capturadas para análise
    "perdas_sobras":           "perdas_sobras",      # litros (Perdas/Sobras)
    "perdas_sobras_pct":       "perdas_sobras_pct",  # percentual (Perdas/Sobras%)
    "perdas_sobras_":          "_ignorar",           # fallback (não deve ocorrer)
    # diferença entre estoques
    "diferenca_em_l":          "diferenca_l",        # Diferença em L (medidor vs escritural)
    "diferenca_em_":           "_ignorar",
    "diferenca__":             "_ignorar",
    "diferenca":               "_ignorar",
}

# Palavras que indicam linha de total/subtotal — devem ser descartadas
_PALAVRAS_TOTAL = {
    "total", "subtotal", "sub-total", "sub total",
    "acumulado", "soma", "resumo", "consolidado",
}

# Palavras-chave que identificam a linha de cabeçalho real
_PALAVRAS_CABECALHO = {
    "data", "abertura", "entrada", "saida", "fechamento",
    "estoque", "medidor", "folha", "escritural",
}


# ---------------------------------------------------------------------------
# LMC — Detecção de formato
# ---------------------------------------------------------------------------

def _detectar_formato_lmc(df_raw: pd.DataFrame) -> str:
    """
    Analisa as colunas do DataFrame bruto e decide:
      'simples'  → planilha MVP com as 6 colunas padrão
      'real'     → relatório exportado de sistema de posto

    Casos cobertos:
      - Arquivo real começa com linhas de título (nome do relatório, posto,
        período) → pandas gera colunas 'Unnamed: 0', 'Unnamed: 1' etc.
        Nesses casos a maioria das colunas será unnamed → formato real.
      - Arquivo real com cabeçalho na primeira linha mas colunas diferentes
        das do MVP → indicadores_real detectam.
      - Arquivo MVP com 6 colunas padrão → simples.
    """
    colunas_norm = [_normalizar_coluna(str(c)) for c in df_raw.columns]
    colunas_set = set(colunas_norm)

    # Se mais da metade das colunas são "unnamed_*", o arquivo começa com
    # linhas de título/cabeçalho múltiplo — definitivamente formato real
    n_unnamed = sum(1 for c in colunas_norm if c.startswith("unnamed"))
    if n_unnamed >= max(1, len(colunas_norm) // 2):
        return "real"

    # Arquivo MVP simples: se as 6 colunas obrigatórias estão presentes (incluindo "tanque"),
    # é formato simples — mesmo que tenha colunas extras como perdas_sobras.
    # Verificamos ANTES dos indicadores_real porque "perdas_sobras" pode aparecer em
    # planilhas simples como coluna adicional, sem indicar formato exportado de sistema.
    colunas_mvp = {"data", "tanque", "estoque_inicial", "entradas", "vendas", "estoque_final"}
    if colunas_mvp <= colunas_set:
        return "simples"

    # Colunas exclusivas do formato real (relatório exportado de sistema de posto)
    # — só chegamos aqui se "tanque" NÃO está nas colunas (produto vem de blocos de texto).
    indicadores_real = {
        "abertura", "fechamento", "escritural", "afericao",
        "saida", "saidas", "perdas_sobras", "estoque_medidor",
        "folha", "diferenca_em_l", "perdas_e_sobras_lmc",
    }
    if colunas_set & indicadores_real:
        return "real"

    # Se há coluna "produto" sem "tanque", provavelmente real
    if "produto" in colunas_set and "tanque" not in colunas_set:
        return "real"

    # Fallback conservador: tenta como real (mais tolerante a variações)
    return "real"


# ---------------------------------------------------------------------------
# LMC — Limpeza para o formato real (PDF → Excel)
# ---------------------------------------------------------------------------

def _encontrar_linha_cabecalho(df_raw: pd.DataFrame) -> int:
    """
    Percorre as primeiras 30 linhas do DataFrame bruto (sem cabeçalho)
    e retorna o índice da linha que MAIS se parece com um cabeçalho real.

    Critério de pontuação: número de células que contêm palavras de
    _PALAVRAS_CABECALHO. Retorna a linha de maior pontuação (≥2 acertos).

    Linhas de produto ("Produto: X") são explicitamente ignoradas, pois
    algumas planilhas reais têm "Estoque" no nome do bloco de produto,
    o que enganaria uma simples busca pela primeira linha com ≥2 matches.
    """
    melhor_idx = 0
    melhor_pontuacao = 0

    for i, row in df_raw.head(30).iterrows():
        # Ignora linhas de produto (ex: "Produto: ETANOL HIDRATADO...")
        if _linha_e_produto(row) is not None:
            continue

        valores = [_celula_texto(v) for v in row.values]
        acertos = sum(
            1 for v in valores
            if any(kw in v for kw in _PALAVRAS_CABECALHO)
        )
        if acertos > melhor_pontuacao:
            melhor_pontuacao = acertos
            melhor_idx = int(i)

    if melhor_pontuacao < 2:
        return 0  # fallback: assume primeira linha
    return melhor_idx


_INDICADORES_SUBHEADER = {
    # unidades físicas
    "l", "m3", "litros", "litro",
    # unidades monetárias
    "r$", "rs", "reais",
    # percentuais
    "%",
    # indicadores de formato de data
    "dd/mm/aa", "dd/mm/aaaa", "dd/mm/yyyy", "mm/aaaa",
    # outros marcadores comuns
    "s/n", "n/a", "-",
}


def _linha_e_subheader(row: pd.Series) -> bool:
    """
    Retorna True se a linha parece ser um sub-cabeçalho de unidades/formato
    (ex: a linha logo abaixo do cabeçalho com 'L', 'DD/MM/AA', '%', ...).

    Critério: pelo menos metade das células não-vazias são indicadores conhecidos.
    """
    celulas = [_celula_texto(v) for v in row.values if _celula_texto(v)]
    if not celulas:
        return False
    matches = sum(1 for c in celulas if c in _INDICADORES_SUBHEADER)
    return matches >= max(1, len(celulas) // 2)


def _linha_e_cabecalho_repetido(row: pd.Series, nomes_cabecalho: List[str]) -> bool:
    """
    Retorna True se a linha é uma repetição do cabeçalho (alguns sistemas
    imprimem o cabeçalho antes de cada bloco de produto).
    Critério: ao menos 3 células coincidem com os nomes do cabeçalho original.
    """
    nomes_set = {_normalizar_coluna(n) for n in nomes_cabecalho if n}
    celulas = [_normalizar_coluna(_celula_texto(v)) for v in row.values]
    coincidencias = sum(1 for c in celulas if c and c in nomes_set)
    return coincidencias >= 3


def _linha_e_total(row: pd.Series) -> bool:
    """Retorna True se a linha parece ser de total, subtotal ou rodapé."""
    valores_texto = [_celula_texto(v) for v in row.values if not pd.isna(v) and str(v).strip()]
    for v in valores_texto:
        for palavra in _PALAVRAS_TOTAL:
            if palavra in v:
                return True
    return False


def _linha_e_produto(row: pd.Series) -> Optional[str]:
    """
    Se a linha contém uma declaração de produto (ex: "Produto: GASOLINA COMUM"),
    retorna o nome do produto. Caso contrário, retorna None.
    """
    for v in row.values:
        texto = _celula_texto(v)
        if texto.startswith("produto"):
            # Remove "produto:" e variações, pega o restante
            nome = re.sub(r"^produto\s*[:–\-]?\s*", "", str(v).strip(), flags=re.IGNORECASE)
            return nome.strip() or "Produto desconhecido"
        # Variações: "Combustível:", "Tanque:", "Produto -"
        for prefixo in ("combustivel", "tanque", "produto"):
            if texto.startswith(prefixo) and len(texto) > len(prefixo) + 1:
                nome = re.sub(
                    rf"^{prefixo}\s*[:–\-]?\s*", "", str(v).strip(), flags=re.IGNORECASE
                )
                return nome.strip() or "Produto desconhecido"
    return None


def _linha_e_vazia(row: pd.Series) -> bool:
    """Retorna True se a linha está completamente vazia ou só tem brancos."""
    return all(pd.isna(v) or str(v).strip() == "" for v in row.values)


def _limpar_lmc_real(caminho: Path) -> pd.DataFrame:
    """
    Lê e normaliza um LMC no formato real (exportado de sistema de posto).

    Retorna DataFrame com as colunas internas:
        data | tanque | estoque_inicial | entradas | vendas | estoque_final

    Passos:
      1. Carrega sem cabeçalho para ter acesso bruto a todas as linhas
      2. Localiza a linha de cabeçalho real (pode não ser a linha 0)
      3. Extrai os nomes das colunas da linha de cabeçalho (apenas essa linha)
      4. Detecta e pula sub-cabeçalho de unidades (L, %, DD/MM/AA ...)
      5. Percorre as linhas detectando blocos de produto e linhas de dados
         — ignora vazias, totais, sub-totais e cabeçalhos repetidos
      6. Mapeia colunas brutas para nomes internos via _MAPA_COLUNAS_REAL
      7. Mantém apenas as 6 colunas obrigatórias + tanque
    """
    # --- 1. Carga bruta sem cabeçalho ---
    df_raw = _carregar_arquivo(caminho, header=None)
    df_raw = df_raw.fillna("")

    # --- 2. Localizar linha de cabeçalho ---
    idx_cab = _encontrar_linha_cabecalho(df_raw)
    logger.debug("Cabeçalho LMC real detectado na linha %d", idx_cab)

    # --- 3. Nomes das colunas (SOMENTE a linha do cabeçalho, sem mesclar) ---
    # Colunas que terminam em "%" recebem sufixo " PCT" antes da normalização
    # para evitar colisão com a coluna de mesmo nome sem "%"
    # (ex: "Perdas/Sobras" e "Perdas/Sobras%" ambas normalizariam para "perdas_sobras")
    nomes_colunas = []
    for i, v in enumerate(df_raw.iloc[idx_cab].values):
        nome = str(v).strip() if str(v).strip() else f"_col{i}"
        if nome.endswith("%"):
            nome = nome[:-1].rstrip() + " PCT"
        nomes_colunas.append(nome)

    # --- 4. Detectar se a próxima linha é sub-cabeçalho de unidades ---
    inicio_dados = idx_cab + 1
    if inicio_dados < len(df_raw):
        prox = df_raw.iloc[inicio_dados]
        if _linha_e_subheader(prox):
            logger.debug("Sub-cabeçalho de unidades detectado na linha %d — ignorado", inicio_dados)
            inicio_dados += 1

    # --- 5. Percorrer linhas de dados ---
    # Pré-scan: verifica se há marcador de produto nas linhas ANTES do início
    # dos dados (ex: produto declarado antes do cabeçalho)
    produto_atual = "Produto não identificado"
    for j in range(0, inicio_dados):
        nome_pre = _linha_e_produto(df_raw.iloc[j])
        if nome_pre:
            produto_atual = nome_pre
            logger.debug("Produto pré-cabeçalho detectado na linha %d: '%s'", j, produto_atual)

    registros_raw: List[dict] = []

    for i in range(inicio_dados, len(df_raw)):
        row = df_raw.iloc[i]

        if _linha_e_vazia(row):
            continue

        if _linha_e_total(row):
            logger.debug("Linha %d descartada (total/subtotal)", i)
            continue

        # Cabeçalho repetido (antes de cada bloco de produto em alguns sistemas)
        if _linha_e_cabecalho_repetido(row, nomes_colunas):
            logger.debug("Linha %d descartada (cabeçalho repetido)", i)
            continue

        nome_produto = _linha_e_produto(row)
        if nome_produto:
            produto_atual = nome_produto
            logger.debug("Linha %d: produto = '%s'", i, produto_atual)
            continue

        # Linha de dados: zip com os nomes do cabeçalho
        registro: dict = {
            col: str(val).strip()
            for col, val in zip(nomes_colunas, row.values)
        }
        registro["__tanque__"] = produto_atual
        registros_raw.append(registro)

    if not registros_raw:
        raise ValueError(
            "Nenhuma linha de dados encontrada no LMC real. "
            f"Cabeçalho detectado na linha {idx_cab}. "
            "Verifique se o arquivo contém linhas de dados abaixo do cabeçalho."
        )

    df = pd.DataFrame(registros_raw)

    # --- 6. Mapear colunas brutas → nomes internos ---
    # Constrói um mapeamento coluna_original → nome_interno
    # usando _MAPA_COLUNAS_REAL. Cada nome interno só pode ser
    # atribuído uma vez (primeira ocorrência vence).
    nomes_ja_usados: set[str] = set()
    cols_para_manter: dict[str, str] = {}   # col_bruta → nome_interno

    for col in df.columns:
        if col == "__tanque__":
            cols_para_manter[col] = col
            continue
        interno = _MAPA_COLUNAS_REAL.get(_normalizar_coluna(col))
        if interno and interno != "_ignorar" and interno not in nomes_ja_usados:
            cols_para_manter[col] = interno
            nomes_ja_usados.add(interno)
        # colunas sem mapeamento ou marcadas _ignorar → descartadas

    # Seleciona e renomeia apenas as colunas mapeadas
    colunas_existentes = [c for c in cols_para_manter if c in df.columns]
    df = df[colunas_existentes].rename(columns=cols_para_manter)

    # --- 7. Preencher coluna tanque ---
    if "__tanque__" in df.columns:
        df["tanque"] = df["__tanque__"]
        df = df.drop(columns=["__tanque__"])

    # --- Filtro final: apenas linhas com data válida ---
    def _tem_data_valida(v) -> bool:
        try:
            _para_date(v)
            return True
        except Exception:
            return False

    if "data" in df.columns:
        mascara = df["data"].apply(_tem_data_valida)
        removidas = (~mascara).sum()
        df = df[mascara].copy()
        if removidas:
            logger.debug("%d linha(s) removidas por data inválida.", removidas)

    logger.info(
        "LMC real pré-processado: %d linhas, %d produto(s), colunas=%s",
        len(df),
        df["tanque"].nunique() if "tanque" in df.columns else 0,
        list(df.columns),
    )
    return df


# ---------------------------------------------------------------------------
# LMC — Parser unificado (formato simples + formato real)
# ---------------------------------------------------------------------------

COLUNAS_LMC = ["data", "tanque", "estoque_inicial", "entradas", "vendas", "estoque_final"]


def carregar_lmc(
    caminho: Path,
    posto: str = "Não informado",
) -> List[RegistroLMC]:
    """
    Lê lmc.xlsx/.xls/.csv/.pdf e retorna lista de RegistroLMC validados.

    Detecta automaticamente o formato:
      - .pdf              : extração via pdfplumber (pdf_parser.py)
      - .xlsx/.xls/.csv  : formato simples (MVP) ou formato real (posto)
    """
    sufixo = caminho.suffix.lower()

    # ------------------------------------------------------------------ PDF
    if sufixo == ".pdf":
        logger.info("LMC '%s': formato PDF detectado.", caminho.name)
        try:
            df, pdf_info = _carregar_pdf_lmc(caminho)
        except ImportError as exc:
            raise ValueError(str(exc)) from exc
        except Exception as exc:
            raise ValueError(
                f"Não foi possível ler o PDF '{caminho.name}': {exc}\n"
                "Verifique se o arquivo contém tabelas digitais (não escaneadas)."
            ) from exc

        # Registra avisos de extração parcial no log
        for aviso in pdf_info.get("avisos", []):
            logger.warning("[PDF] %s", aviso)

        logger.info(
            "LMC PDF: %d pág. lida(s) de %d, %d produto(s): %s",
            pdf_info.get("paginas_lidas", 0),
            pdf_info.get("paginas_total", 0),
            len(pdf_info.get("produtos_encontrados", [])),
            pdf_info.get("produtos_encontrados", []),
        )

        # Normaliza colunas (o pdf_parser já mapeia, mas normaliza por segurança)
        df.columns = [_normalizar_coluna(c) for c in df.columns]

        # Verifica colunas obrigatórias
        faltando = [c for c in COLUNAS_LMC if c not in df.columns]
        if faltando:
            raise ValueError(
                f"[LMC — PDF] Colunas obrigatórias não encontradas: {faltando}.\n"
                f"Colunas extraídas do PDF: {list(df.columns)}\n"
                "Dica: verifique se o relatório contém as colunas "
                "Abertura, Entrada, Saída e Fechamento."
            )

        # Constrói registros
        registros: List[RegistroLMC] = []
        erros: List[Tuple[int, str]] = []
        for idx, row in df.iterrows():
            try:
                registros.append(RegistroLMC(
                    data=_para_date(row["data"]),
                    tanque=str(row.get("tanque", "Produto desconhecido")).strip(),
                    estoque_inicial=_para_float(row["estoque_inicial"]),
                    entradas=_para_float(row["entradas"]),
                    vendas=_para_float(row["vendas"]),
                    estoque_final=_para_float(row["estoque_final"]),
                    posto=posto,
                    perdas_sobras=_para_float(row.get("perdas_sobras", 0)),
                    perdas_sobras_pct=_para_float(row.get("perdas_sobras_pct", 0)),
                    diferenca_l=_para_float(row.get("diferenca_l", 0)),
                ))
            except Exception as exc:
                erros.append((int(idx) + 2, str(exc)))

        for linha, msg in erros:
            logger.warning("LMC PDF linha %d ignorada: %s", linha, msg)

        logger.info(
            "LMC carregado [PDF]: %d registros válidos, %d ignorados.",
            len(registros), len(erros),
        )
        return registros

    # -------------------------------------------------------- Excel / CSV
    # Primeiro carregamento para detectar formato
    df_probe = _carregar_arquivo(caminho)
    formato = _detectar_formato_lmc(df_probe)
    logger.info("LMC '%s': formato detectado = '%s'", caminho.name, formato)

    if formato == "real":
        try:
            df = _limpar_lmc_real(caminho)
        except Exception as exc:
            logger.warning(
                "Falha ao processar LMC como formato real (%s). "
                "Tentando como formato simples...", exc
            )
            df = df_probe
            df = _normalizar_colunas(df)
    else:
        df = df_probe
        df = _normalizar_colunas(df)

    # Normaliza colunas do df (formato real já tem nomes internos, mas normaliza por segurança)
    df.columns = [_normalizar_coluna(c) for c in df.columns]

    # Verifica colunas obrigatórias — com mensagem clara se falhar
    faltando = [c for c in COLUNAS_LMC if c not in df.columns]
    if faltando:
        disponiveis = list(df.columns)
        raise ValueError(
            f"[LMC — {formato}] Colunas obrigatórias não encontradas: {faltando}.\n"
            f"Colunas disponíveis após normalização: {disponiveis}\n"
            f"Dica: verifique o mapeamento em _MAPA_COLUNAS_REAL ou adicione "
            f"a coluna faltante ao arquivo."
        )

    # Construção dos registros
    registros: List[RegistroLMC] = []
    erros: List[Tuple[int, str]] = []

    for idx, row in df.iterrows():
        try:
            reg = RegistroLMC(
                data=_para_date(row["data"]),
                tanque=str(row.get("tanque", "Tanque desconhecido")).strip(),
                estoque_inicial=_para_float(row["estoque_inicial"]),
                entradas=_para_float(row["entradas"]),
                vendas=_para_float(row["vendas"]),
                estoque_final=_para_float(row["estoque_final"]),
                posto=posto,
                perdas_sobras=_para_float(row.get("perdas_sobras", 0)),
                perdas_sobras_pct=_para_float(row.get("perdas_sobras_pct", 0)),
                diferenca_l=_para_float(row.get("diferenca_l", 0)),
            )
            registros.append(reg)
        except Exception as exc:
            erros.append((int(idx) + 2, str(exc)))

    if erros:
        for linha, msg in erros:
            logger.warning("LMC linha %d ignorada: %s", linha, msg)

    logger.info(
        "LMC carregado [%s]: %d registros válidos, %d ignorados.",
        formato, len(registros), len(erros),
    )
    return registros


# ---------------------------------------------------------------------------
# Parser: Caixa
# ---------------------------------------------------------------------------

COLUNAS_CAIXA = ["data", "operador", "dinheiro", "cartao", "pix", "sangria", "total_informado"]


def carregar_caixa(caminho: Path, posto: str = "Não informado") -> List[RegistroCaixa]:
    """Lê caixa.csv/.xlsx/.pdf e retorna lista de RegistroCaixa validados."""
    if caminho.suffix.lower() == ".pdf":
        logger.info("CAIXA '%s': formato PDF detectado.", caminho.name)
        from app.services.pdf_caixa_parser import parsear_caixa_pdf
        return parsear_caixa_pdf(caminho, posto=posto)

    df_raw = _carregar_arquivo(caminho)

    # Detecta se é o formato "Prestação de Contas Sintético" (Quality Automação)
    from app.services.xlsx_caixa_parser import e_formato_sintetico, parsear_caixa_xlsx_sintetico
    if e_formato_sintetico(df_raw):
        logger.info("CAIXA '%s': formato sintético detectado.", caminho.name)
        return parsear_caixa_xlsx_sintetico(caminho, posto=posto)

    df = _normalizar_colunas(df_raw)
    # Diagnóstico amigável: detecta se o usuário enviou o arquivo errado
    colunas_set = set(df.columns)
    indicadores_lmc = {"tanque", "estoque_inicial", "entradas", "vendas", "estoque_final",
                       "abertura", "fechamento", "movimentacao_de_bicos", "bico", "encerrante"}
    if colunas_set & indicadores_lmc:
        raise ValueError(
            "O arquivo enviado parece ser um relatório de LMC ou bicos, não um fechamento de caixa.\n"
            "Envie o arquivo CSV/XLSX de fechamento de caixa com as colunas: "
            "data, operador, dinheiro, cartao, pix, sangria, total_informado.\n"
            "Para PDFs de caixa (formato 'Caixa Apresentado'), envie o arquivo .pdf diretamente."
        )
    _validar_colunas(df, COLUNAS_CAIXA, str(caminho))

    registros: List[RegistroCaixa] = []
    erros: List[Tuple[int, str]] = []

    for idx, row in df.iterrows():
        try:
            reg = RegistroCaixa(
                data=_para_date(row["data"]),
                operador=str(row["operador"]).strip(),
                dinheiro=_para_float(row["dinheiro"]),
                cartao=_para_float(row["cartao"]),
                pix=_para_float(row["pix"]),
                sangria=_para_float(row["sangria"]),
                total_informado=_para_float(row["total_informado"]),
                posto=posto,
            )
            registros.append(reg)
        except Exception as exc:
            erros.append((int(idx) + 2, str(exc)))

    if erros:
        for linha, msg in erros:
            logger.warning("CAIXA linha %d ignorada: %s", linha, msg)

    logger.info("CAIXA carregado: %d registros válidos, %d ignorados.", len(registros), len(erros))
    return registros


# ---------------------------------------------------------------------------
# Parser: Aferição
# ---------------------------------------------------------------------------

COLUNAS_AFERICAO = ["data", "bomba", "litros_testados", "litros_medidos", "erro"]


def carregar_afericao(caminho: Path, posto: str = "Não informado") -> List[RegistroAfericao]:
    """Lê afericao.xlsx e retorna lista de RegistroAfericao validados."""
    df = _carregar_arquivo(caminho)
    df = _normalizar_colunas(df)
    _validar_colunas(df, COLUNAS_AFERICAO, str(caminho))

    registros: List[RegistroAfericao] = []
    erros: List[Tuple[int, str]] = []

    for idx, row in df.iterrows():
        try:
            litros_testados = _para_float(row["litros_testados"])
            litros_medidos = _para_float(row["litros_medidos"])

            # Recalcula erro percentual para garantir consistência;
            # usa o valor do arquivo apenas como referência se testados == 0
            if litros_testados != 0:
                erro_calculado = abs((litros_medidos - litros_testados) / litros_testados) * 100
            else:
                erro_calculado = _para_float(row["erro"])

            reg = RegistroAfericao(
                data=_para_date(row["data"]),
                bomba=str(row["bomba"]).strip(),
                litros_testados=litros_testados,
                litros_medidos=litros_medidos,
                erro=round(erro_calculado, 4),
                posto=posto,
            )
            registros.append(reg)
        except Exception as exc:
            erros.append((int(idx) + 2, str(exc)))

    if erros:
        for linha, msg in erros:
            logger.warning("AFERIÇÃO linha %d ignorada: %s", linha, msg)

    logger.info("AFERIÇÃO carregada: %d registros válidos, %d ignorados.", len(registros), len(erros))
    return registros


# ---------------------------------------------------------------------------
# Descoberta automática de arquivos na pasta de entrada
# ---------------------------------------------------------------------------

def descobrir_arquivos(pasta_entrada: Path) -> dict[str, Path | None]:
    """
    Procura pelos arquivos esperados dentro de `pasta_entrada`.
    Retorna dict com as chaves 'lmc', 'caixa', 'afericao' apontando para
    o Path encontrado ou None se ausente.
    """
    mapa: dict[str, Path | None] = {"lmc": None, "caixa": None, "afericao": None}

    _ext_tabela = (".xlsx", ".xls", ".csv")
    _ext_lmc    = (".xlsx", ".xls", ".csv", ".pdf")

    for arquivo in pasta_entrada.iterdir():
        nome = arquivo.stem.lower()
        if "lmc" in nome and arquivo.suffix.lower() in _ext_lmc:
            mapa["lmc"] = arquivo
        elif "caixa" in nome and arquivo.suffix.lower() in (*_ext_tabela, ".pdf"):
            mapa["caixa"] = arquivo
        elif ("afericao" in nome or "aferição" in nome) and arquivo.suffix.lower() in _ext_tabela:
            mapa["afericao"] = arquivo

    return mapa
