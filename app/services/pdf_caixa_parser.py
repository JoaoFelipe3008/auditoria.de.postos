"""
pdf_caixa_parser.py — Parser para relatório "Caixa Apresentado" em PDF.

Suporta o formato padrão exportado por sistemas de automação de postos
(ex: Quality Automação, SistemaPosto, etc.) com as colunas:
  Apresentado (R$) | Apurado (R$) | Diferença (R$) | Sangria (R$)

Lógica de mapeamento para RegistroCaixa:
  - operador       → Responsável extraído do cabeçalho
  - data           → Data do turno ("Caixa: 1º TURNO | ... | DD/MM/YYYY")
  - dinheiro       → Dinheiro Apresentado + Notas (dinheiro físico total)
  - cartao         → Cartão Apresentado
  - pix            → Transf. Créd. Apresentado (PIX / transferência)
  - sangria        → Total da seção Sangria
  - total_informado→ Total Apresentado (o que o operador declarou)

  A fórmula do módulo de caixa (dinheiro + cartao + pix − sangria) é calibrada
  para igualar o Total Apurado, de modo que qualquer diferença detectada
  corresponde exatamente ao Apresentado − Apurado do próprio relatório.

Robustez:
  - Funciona independente do número de páginas
  - Ignora linhas de ruído / totais intermediários
  - Retorna lista vazia (com aviso) se o PDF não for reconhecido
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import List, Optional, Tuple

from app.models.schemas import RegistroCaixa

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Padrões de número no formato brasileiro
# ---------------------------------------------------------------------------

_NUM  = r"\d{1,3}(?:\.\d{3})*,\d{2}"   # ex: 36.682,91
_SNUM = r"-?" + _NUM                     # com sinal opcional


def _br(texto: str) -> float:
    """Converte número brasileiro para float. Ex: '36.682,91' → 36682.91"""
    return float(texto.strip().replace(".", "").replace(",", "."))


def _extrair_texto(caminho: Path) -> str:
    """Extrai todo o texto do PDF via pypdf."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(caminho))
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    except ImportError:
        raise ImportError(
            "pypdf não instalado. Execute: pip install pypdf"
        )


# ---------------------------------------------------------------------------
# Extratores individuais
# ---------------------------------------------------------------------------

def _extrair_operador(texto: str) -> str:
    """Extrai o nome do responsável pelo turno."""
    m = re.search(r"Respons[áa]vel:\s*(.+?)(?:\n|$)", texto)
    if m:
        nome = m.group(1).strip()
        # Remove sufixos que às vezes aparecem na mesma linha
        nome = re.split(r"\s{3,}|\|", nome)[0].strip()
        return nome or "Operador não identificado"
    return "Operador não identificado"


def _extrair_data(texto: str) -> date:
    """
    Extrai a data do turno.
    Prioriza o padrão 'Caixa: ... | DD/MM/YYYY'.
    Fallback: primeira data no formato DD/MM/YYYY encontrada no texto.
    """
    # Padrão primário: linha de header do caixa
    m = re.search(r"Caixa:.*?(\d{2}/\d{2}/\d{4})", texto)
    if m:
        try:
            from datetime import datetime
            return datetime.strptime(m.group(1), "%d/%m/%Y").date()
        except ValueError:
            pass

    # Fallback: primeira data válida no documento
    for m in re.finditer(r"(\d{2}/\d{2}/\d{4})", texto):
        try:
            from datetime import datetime
            return datetime.strptime(m.group(1), "%d/%m/%Y").date()
        except ValueError:
            continue

    return date.today()


def _extrair_total_principal(texto: str) -> Tuple[float, float, float]:
    """
    Extrai a linha de Total com Apresentado, Apurado e Diferença.

    Estratégia: busca linha a linha para evitar que o regex multi-linha
    consuma um número de uma linha como terceiro elemento de outra.
    Retorna (apresentado, apurado, diferença) da linha com maior valor.
    """
    melhor = (0.0, 0.0, 0.0)
    for linha in texto.splitlines():
        m = re.search(rf"({_NUM})[ \t]+({_NUM})[ \t]+({_SNUM})", linha)
        if not m:
            continue
        a = _br(m.group(1))
        b = _br(m.group(2))
        c = _br(m.group(3))
        if a > 1_000 and b > 1_000 and a > melhor[0]:
            melhor = (a, b, c)

    if melhor[0] == 0.0:
        logger.warning("PDF Caixa: Total principal não encontrado.")
    return melhor


def _extrair_pares_tabela(texto: str) -> List[Tuple[float, float]]:
    """
    Retorna pares (apresentado, apurado) linha a linha da tabela de pagamentos.
    Para evitar capturar dados de outras tabelas (bicos, clientes), busca apenas
    até a primeira ocorrência de 'Sangria', 'Bicos' ou 'Encerr'.
    """
    # Limita ao trecho relevante (antes da seção de bicos/sangria/encerrantes)
    corte = re.search(r"(?:Sangria|Bicos|Encerr)", texto, re.IGNORECASE)
    trecho = texto[: corte.start()] if corte else texto

    pares = []
    for linha in trecho.splitlines():
        m = re.search(rf"({_NUM})[ \t]+({_NUM})", linha)
        if m:
            a = _br(m.group(1))
            b = _br(m.group(2))
            pares.append((a, b))
    return pares


def _extrair_dinheiro(pares: List[Tuple[float, float]], total: float) -> float:
    """
    Dinheiro = primeiro par onde ambos os valores são > 100
    e < 60% do total (exclui o par do Total geral).
    """
    limite_superior = total * 0.6
    for a, b in pares:
        if 100 < a < limite_superior and 100 < b < limite_superior:
            return a
    # Fallback: primeiro par positivo
    for a, _ in pares:
        if 10 < a < limite_superior:
            return a
    return 0.0


def _extrair_cartao(
    pares: List[Tuple[float, float]],
    dinheiro: float,
    total: float,
) -> float:
    """
    Cartão = segundo par distinto do dinheiro onde ambos > 100 e < 60% do total.
    Tipicamente o Cartão é a segunda linha de pagamento significativo.
    """
    limite_superior = total * 0.6
    for a, b in pares:
        if (
            100 < a < limite_superior
            and 100 < b < limite_superior
            and abs(a - dinheiro) > 1
        ):
            return a
    return 0.0


def _extrair_pix(texto: str) -> float:
    """
    Transf. Créd = PIX em sistemas modernos.
    Busca 'Transf. Cr' ou 'Pix' no texto e pega o primeiro valor positivo seguinte.
    """
    m = re.search(
        r"(?:Transf[.º]?\s*Cr[eé]d|PIX|Pix)[:\s]*\n?([^\n]*\n?[^\n]*?)(" + _NUM + r")",
        texto,
        re.IGNORECASE,
    )
    if m:
        v = _br(m.group(2))
        if v > 0:
            return v
    return 0.0


def _extrair_sangria(texto: str) -> float:
    """
    Extrai o total de sangria do bloco 'Sangria (R$) ... Serviço'.
    Retorna o último valor positivo maior que zero nessa seção,
    que normalmente é o subtotal/total da sangria.
    """
    m = re.search(
        r"Sangria\s*\(R\$\)(.*?)(?:Servi[çc]o|Bicos|Encerr)",
        texto,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return 0.0

    nums = [_br(n) for n in re.findall(_NUM, m.group(1))]
    positivos = [n for n in nums if n > 0]
    return positivos[-1] if positivos else 0.0


def _extrair_posto(texto: str) -> Optional[str]:
    """Tenta extrair o nome do posto da primeira linha do documento."""
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    for linha in linhas[:5]:  # nas primeiras 5 linhas
        if re.search(r"POSTO|AUTO\s*POSTO|POSTO\s+DE", linha, re.IGNORECASE):
            return linha
    return None


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def parsear_caixa_pdf(
    caminho: Path,
    posto: str = "Não informado",
) -> List[RegistroCaixa]:
    """
    Lê um PDF de 'Caixa Apresentado' e retorna lista de RegistroCaixa.

    Em caso de falha na extração dos valores essenciais (total),
    retorna lista vazia com log de aviso — não lança exceção,
    para não interromper auditorias com múltiplos arquivos.
    """
    logger.info("PDF Caixa: lendo '%s'", caminho.name)

    try:
        texto = _extrair_texto(caminho)
    except Exception as exc:
        logger.error("PDF Caixa: erro ao extrair texto de '%s': %s", caminho.name, exc)
        return []

    # Extrai posto do PDF, se não fornecido
    posto_pdf = _extrair_posto(texto)
    posto_final = posto if posto and posto != "Não informado" else (posto_pdf or posto)

    operador       = _extrair_operador(texto)
    data           = _extrair_data(texto)
    total_apres, total_apur, diferenca = _extrair_total_principal(texto)

    if total_apres == 0.0:
        logger.warning(
            "PDF Caixa: '%s' — não foi possível extrair o Total. "
            "Arquivo pode ser um formato não suportado.",
            caminho.name,
        )
        return []

    pares      = _extrair_pares_tabela(texto)
    dinheiro   = _extrair_dinheiro(pares, total_apres)
    cartao     = _extrair_cartao(pares, dinheiro, total_apres)
    pix        = _extrair_pix(texto)
    sangria    = _extrair_sangria(texto)

    # Calibração: ajusta pix para que a fórmula do audit reproduza
    # exatamente o Total Apurado → qualquer diferença detectada = Apresentado − Apurado
    # dinheiro + cartao + pix_cal − sangria = total_apur
    pix_calibrado = total_apur - dinheiro - cartao + sangria
    if pix > 0 and abs(pix - pix_calibrado) < 1.0:
        pix_final = pix  # valor extraído é consistente
    else:
        pix_final = pix_calibrado  # usa calibração

    registro = RegistroCaixa(
        data=data,
        operador=operador,
        dinheiro=round(dinheiro, 2),
        cartao=round(cartao, 2),
        pix=round(pix_final, 2),
        sangria=round(sangria, 2),
        total_informado=round(total_apres, 2),
        posto=posto_final,
    )

    logger.info(
        "PDF Caixa: '%s' → %s | %s | apresentado=%.2f | apurado=%.2f | dif=%.2f | sangria=%.2f",
        caminho.name, operador, data,
        total_apres, total_apur, diferenca, sangria,
    )

    return [registro]
