"""
dashboard.py — Interface web do Sistema de Auditoria de Postos de Combustíveis.

Como executar:
    streamlit run app/ui/dashboard.py

Conecta diretamente aos módulos existentes:
    parser_service → auditoria_service → relatorio_service
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Garante que o root do projeto está no path independente de onde o Streamlit for chamado
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from app.models.schemas import (
    ConfiguracaoTolerancia,
    Divergencia,
    NivelRisco,
    ResultadoAuditoria,
    TipoDivergencia,
)
from app.services.auditoria_service import AuditoriaService
from app.services.historico_service import HistoricoService
from app.services.parser_service import carregar_afericao, carregar_caixa, carregar_lmc
from app.services.relatorio_service import (
    gerar_relatorio_csv,
    gerar_relatorio_json,
    gerar_relatorio_txt,
)

# ---------------------------------------------------------------------------
# Configuração da página
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Auditoria Inteligente de Postos",
    page_icon="⛽",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# CSS customizado — visual limpo e profissional
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
    /* Cabeçalho principal */
    .main-header {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        padding: 2rem 2.5rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        color: white;
    }
    .main-header h1 { margin: 0; font-size: 2rem; font-weight: 700; }
    .main-header p  { margin: 0.25rem 0 0; opacity: 0.75; font-size: 1rem; }

    /* Cards de métricas */
    .metric-card {
        background: white;
        border: 1px solid #e5e7eb;
        border-radius: 10px;
        padding: 1.2rem 1.5rem;
        text-align: center;
        box-shadow: 0 1px 4px rgba(0,0,0,.06);
    }
    .metric-card .value { font-size: 2.2rem; font-weight: 700; line-height: 1; }
    .metric-card .label { font-size: 0.8rem; color: #6b7280; margin-top: 0.3rem; text-transform: uppercase; letter-spacing: .05em; }

    /* Badge de risco */
    .badge-critico { background:#fef2f2; color:#dc2626; border:1px solid #fca5a5; border-radius:6px; padding:2px 10px; font-weight:600; font-size:.8rem; }
    .badge-alto    { background:#fff7ed; color:#ea580c; border:1px solid #fdba74; border-radius:6px; padding:2px 10px; font-weight:600; font-size:.8rem; }
    .badge-medio   { background:#fefce8; color:#ca8a04; border:1px solid #fde047; border-radius:6px; padding:2px 10px; font-weight:600; font-size:.8rem; }
    .badge-baixo   { background:#f0fdf4; color:#16a34a; border:1px solid #86efac; border-radius:6px; padding:2px 10px; font-weight:600; font-size:.8rem; }

    /* Card de alerta */
    .alert-card {
        border-left: 4px solid;
        border-radius: 0 8px 8px 0;
        padding: 0.9rem 1.1rem;
        margin-bottom: 0.6rem;
        background: white;
        box-shadow: 0 1px 3px rgba(0,0,0,.05);
    }
    .alert-critico { border-color: #dc2626; background: #fef2f2; }
    .alert-alto    { border-color: #ea580c; background: #fff7ed; }
    .alert-medio   { border-color: #ca8a04; background: #fefce8; }
    .alert-baixo   { border-color: #16a34a; background: #f0fdf4; }
    .alert-title   { font-weight: 600; font-size: 0.95rem; margin-bottom: 0.2rem; }
    .alert-body    { font-size: 0.82rem; color: #4b5563; line-height: 1.5; }

    /* Seção de upload */
    .upload-section {
        background: #f8fafc;
        border: 2px dashed #cbd5e1;
        border-radius: 10px;
        padding: 1.2rem;
        text-align: center;
    }
    .upload-section h4 { margin: 0 0 0.5rem; color: #334155; }

    /* Status geral */
    .status-ok       { background:#f0fdf4; border:1px solid #86efac; color:#166534; border-radius:8px; padding:.8rem 1.2rem; font-weight:600; }
    .status-atencao  { background:#fefce8; border:1px solid #fde047; color:#854d0e; border-radius:8px; padding:.8rem 1.2rem; font-weight:600; }
    .status-critico  { background:#fef2f2; border:1px solid #fca5a5; color:#991b1b; border-radius:8px; padding:.8rem 1.2rem; font-weight:600; }

    /* Ocultar rodapé padrão do Streamlit */
    footer { visibility: hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

PASTA_EXEMPLOS = ROOT / "data" / "entradas"
PASTA_RELATORIOS = ROOT / "data" / "relatorios"

# Instância única do serviço de histórico (cria o banco se não existir)
_historico = HistoricoService()

_ICONE_TIPO = {
    TipoDivergencia.LMC:         "📦",
    TipoDivergencia.CAIXA:       "💰",
    TipoDivergencia.AFERICAO:    "⚙️",
    TipoDivergencia.PERDA_SOBRA: "🔻",
}

_NOME_TIPO = {
    TipoDivergencia.LMC:         "LMC",
    TipoDivergencia.CAIXA:       "Caixa",
    TipoDivergencia.AFERICAO:    "Aferição",
    TipoDivergencia.PERDA_SOBRA: "Perdas/Sobras",
}

_CSS_NIVEL = {
    NivelRisco.CRITICO: ("alert-critico", "badge-critico"),
    NivelRisco.ALTO:    ("alert-alto",    "badge-alto"),
    NivelRisco.MEDIO:   ("alert-medio",   "badge-medio"),
    NivelRisco.BAIXO:   ("alert-baixo",   "badge-baixo"),
}


# ---------------------------------------------------------------------------
# Helpers de UI
# ---------------------------------------------------------------------------

def _render_metric(label: str, value: str | int, cor: str = "#1e293b") -> None:
    st.markdown(
        f"""<div class="metric-card">
              <div class="value" style="color:{cor}">{value}</div>
              <div class="label">{label}</div>
            </div>""",
        unsafe_allow_html=True,
    )


def _render_alerta(div: Divergencia) -> None:
    css_card, css_badge = _CSS_NIVEL[div.nivel_risco]
    icone = _ICONE_TIPO.get(div.tipo, "")
    nome_tipo = _NOME_TIPO.get(div.tipo, div.tipo.value)

    st.markdown(
        f"""<div class="alert-card {css_card}">
              <div class="alert-title">
                {icone} {nome_tipo} — {div.referencia}
                &nbsp;<span class="{css_badge}">{div.nivel_risco.value}</span>
              </div>
              <div class="alert-body">
                <strong>Ocorrência:</strong> {div.data.strftime('%d/%m/%Y')}<br>
                <strong>Detalhe:</strong> {div.descricao}<br>
                <strong>Causa provável:</strong> {div.causa_provavel}<br>
                <strong>Recomendação:</strong> {div.recomendacao}
              </div>
            </div>""",
        unsafe_allow_html=True,
    )


def _status_geral(resultado: ResultadoAuditoria) -> None:
    if resultado.divergencias_criticas > 0:
        st.markdown(
            f'<div class="status-critico">🚨 SITUAÇÃO CRÍTICA — '
            f'{resultado.divergencias_criticas} ocorrência(s) crítica(s) exigem ação imediata.</div>',
            unsafe_allow_html=True,
        )
    elif resultado.divergencias_alto_risco > 0:
        st.markdown(
            f'<div class="status-atencao">⚠️ ATENÇÃO — '
            f'{resultado.divergencias_alto_risco} alerta(s) de alto risco identificados.</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="status-ok">✅ OPERAÇÃO NORMAL — Nenhuma irregularidade grave encontrada.</div>',
            unsafe_allow_html=True,
        )


def _salvar_upload(arquivo_upload, sufixo: str) -> Path:
    """Salva um arquivo de upload do Streamlit em arquivo temporário e retorna o Path."""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=sufixo)
    tmp.write(arquivo_upload.getvalue())
    tmp.flush()
    tmp.close()
    return Path(tmp.name)


# ---------------------------------------------------------------------------
# Lógica de auditoria
# ---------------------------------------------------------------------------

def executar_auditoria(
    path_lmc: Path | None,
    path_caixa: Path | None,
    path_afericao: Path | None,
    nome_posto: str,
    cfg: ConfiguracaoTolerancia,
) -> tuple:
    """Carrega arquivos, executa auditoria e retorna (resultado, lmc, caixa)."""
    lmc      = carregar_lmc(path_lmc, posto=nome_posto)           if path_lmc      else []
    caixa    = carregar_caixa(path_caixa, posto=nome_posto)       if path_caixa    else []
    afericao = carregar_afericao(path_afericao, posto=nome_posto) if path_afericao else []

    service = AuditoriaService(posto=nome_posto, cfg=cfg)
    resultado = service.auditar_registros(
        registros_lmc=lmc,
        registros_caixa=caixa,
        registros_afericao=afericao,
    )
    return resultado, lmc, caixa


# ---------------------------------------------------------------------------
# Sidebar — configurações
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("### ⚙️ Configurações")
    nome_posto = st.text_input("Nome do Posto", value="Posto Exemplo", max_chars=60)

    st.markdown("---")
    st.markdown("**Tolerâncias LMC (litros)**")
    lmc_medio = st.slider("Alerta Médio",  10,  200, 100, step=10)
    lmc_alto  = st.slider("Alerta Alto",   50, 1000, 300, step=50)

    st.markdown("**Tolerâncias Caixa (R$)**")
    caixa_medio = st.slider("Alerta Médio",   5,  500, 100, step=5)
    caixa_alto  = st.slider("Alerta Alto",   50, 2000, 500, step=50)

    st.markdown("**Tolerâncias Aferição (%)**")
    afer_medio = st.slider("Alerta Médio", 0.1, 1.0, 0.5, step=0.1, format="%.1f%%")
    afer_alto  = st.slider("Alerta Alto",  0.5, 2.0, 1.0, step=0.1, format="%.1f%%")

    st.markdown("**Tolerâncias Perdas/Sobras**")
    ps_pct_medio   = st.slider("Alerta Médio (%)",   0.3, 1.5, 0.5, step=0.1, format="%.1f%%",
                               help="Limiar para padrão recorrente (R3)")
    ps_pct_alto    = st.slider("Alerta Alto (%)",    0.5, 3.0, 1.0, step=0.1, format="%.1f%%",
                               help="Limiar para alerta individual por dia (R1)")
    ps_pct_critico = st.slider("Alerta Crítico (%)", 1.0, 5.0, 2.0, step=0.5, format="%.1f%%",
                               help="Limiar crítico — acima disto, ação imediata")
    ps_ruido       = st.slider("Ruído mínimo (L)",   1,   20,  2,   step=1,
                               help="Valores abaixo deste limiar em litros são ignorados")

    limite_sangria = st.number_input(
        "Limite de Sangria (R$)", min_value=500, max_value=20000, value=2000, step=500
    )

    cfg = ConfiguracaoTolerancia(
        lmc_tolerancia_baixo=lmc_medio * 0.3,
        lmc_tolerancia_medio=lmc_medio,
        lmc_tolerancia_alto=lmc_alto,
        caixa_tolerancia_baixo=caixa_medio * 0.1,
        caixa_tolerancia_medio=caixa_medio,
        caixa_tolerancia_alto=caixa_alto,
        afericao_tolerancia_baixo=afer_medio * 0.6,
        afericao_tolerancia_medio=afer_medio,
        afericao_tolerancia_alto=afer_alto,
        perdas_pct_medio=ps_pct_medio,
        perdas_pct_alto=ps_pct_alto,
        perdas_pct_critico=ps_pct_critico,
        perdas_litros_ruido=float(ps_ruido),
    )

    st.markdown("---")
    st.markdown(
        "<small style='color:#94a3b8'>Sistema de Auditoria v1.1<br>"
        "Cálculos 100% determinísticos</small>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Cabeçalho
# ---------------------------------------------------------------------------

st.markdown(
    f"""<div class="main-header">
          <h1>⛽ Auditoria Inteligente de Postos</h1>
          <p>Análise automática de LMC · Perdas e Sobras · Fechamento de Caixa · Aferição de Bombas</p>
        </div>""",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Seção de upload
# ---------------------------------------------------------------------------

st.markdown("### 📂 Arquivos de Entrada")
col_lmc, col_caixa, col_afer = st.columns(3)

with col_lmc:
    st.markdown("**📦 LMC — Livro de Movimentação**")
    upload_lmc = st.file_uploader(
        "lmc.xlsx / lmc.pdf", type=["xlsx", "xls", "csv", "pdf"],
        key="upload_lmc", label_visibility="collapsed",
    )
    if upload_lmc:
        ext = Path(upload_lmc.name).suffix.lower()
        if ext == ".pdf":
            st.success(f"✓ {upload_lmc.name}  📄 PDF detectado")
        else:
            st.success(f"✓ {upload_lmc.name}")

with col_caixa:
    st.markdown("**💰 Fechamento de Caixa**")
    upload_caixa = st.file_uploader(
        "caixa.csv / caixa.pdf", type=["csv", "xlsx", "xls", "pdf"],
        key="upload_caixa", label_visibility="collapsed",
    )
    if upload_caixa:
        ext = Path(upload_caixa.name).suffix.lower()
        if ext == ".pdf":
            st.success(f"✓ {upload_caixa.name}  📄 PDF detectado")
        else:
            st.success(f"✓ {upload_caixa.name}")

with col_afer:
    st.markdown("**⚙️ Aferição de Bombas**")
    upload_afer = st.file_uploader(
        "afericao.xlsx", type=["xlsx", "xls", "csv"],
        key="upload_afer", label_visibility="collapsed",
    )
    if upload_afer:
        st.success(f"✓ {upload_afer.name}")

st.markdown("")

# ---------------------------------------------------------------------------
# Botões de ação
# ---------------------------------------------------------------------------

col_btn1, col_btn2, col_espaco = st.columns([2, 2, 5])

with col_btn1:
    btn_analisar = st.button(
        "🔍 ANALISAR DADOS",
        type="primary",
        use_container_width=True,
        disabled=(not upload_lmc and not upload_caixa and not upload_afer),
    )

with col_btn2:
    btn_exemplo = st.button(
        "🧪 Usar dados de teste",
        use_container_width=True,
        help="Carrega os dados fictícios gerados pelo generate_examples.py",
    )

# ---------------------------------------------------------------------------
# Execução: dados de teste
# ---------------------------------------------------------------------------

if btn_exemplo:
    arquivos_ok = all(
        (PASTA_EXEMPLOS / f).exists()
        for f in ["lmc.xlsx", "caixa.csv", "afericao.xlsx"]
    )
    if not arquivos_ok:
        st.warning(
            "⚠️ Dados de exemplo não encontrados. "
            "Execute `python generate_examples.py` primeiro."
        )
    else:
        with st.spinner("Analisando dados de exemplo..."):
            resultado, lmc_regs, caixa_regs = executar_auditoria(
                path_lmc=PASTA_EXEMPLOS / "lmc.xlsx",
                path_caixa=PASTA_EXEMPLOS / "caixa.csv",
                path_afericao=PASTA_EXEMPLOS / "afericao.xlsx",
                nome_posto=nome_posto or "Posto Exemplo (Teste)",
                cfg=cfg,
            )
        _historico.salvar(resultado, caixa_regs, lmc_regs)
        st.session_state["resultado"] = resultado
        st.session_state["origem"] = "exemplo"

# ---------------------------------------------------------------------------
# Execução: arquivos enviados pelo usuário
# ---------------------------------------------------------------------------

if btn_analisar:
    paths: dict[str, Path | None] = {"lmc": None, "caixa": None, "afericao": None}
    avisos = []

    if upload_lmc:
        sufixo_lmc = Path(upload_lmc.name).suffix.lower() or ".xlsx"
        paths["lmc"] = _salvar_upload(upload_lmc, sufixo_lmc)
    else:
        avisos.append("LMC não enviado — módulo será ignorado.")

    if upload_caixa:
        sufixo_caixa = Path(upload_caixa.name).suffix.lower() or ".csv"
        paths["caixa"] = _salvar_upload(upload_caixa, sufixo_caixa)
    else:
        avisos.append("Caixa não enviado — módulo será ignorado.")

    if upload_afer:
        paths["afericao"] = _salvar_upload(upload_afer, ".xlsx")
    else:
        avisos.append("Aferição não enviada — módulo será ignorado.")

    for aviso in avisos:
        st.info(f"ℹ️ {aviso}")

    # Mensagem de progresso adaptada ao tipo dos arquivos
    _lmc_e_pdf = (
        upload_lmc is not None
        and Path(upload_lmc.name).suffix.lower() == ".pdf"
    )
    _caixa_e_pdf = (
        upload_caixa is not None
        and Path(upload_caixa.name).suffix.lower() == ".pdf"
    )
    _msg_spinner = (
        "Lendo PDF... Aguarde (pode levar alguns segundos)."
        if (_lmc_e_pdf or _caixa_e_pdf)
        else "Analisando dados... Aguarde."
    )

    with st.spinner(_msg_spinner):
        try:
            resultado, lmc_regs, caixa_regs = executar_auditoria(
                path_lmc=paths["lmc"],
                path_caixa=paths["caixa"],
                path_afericao=paths["afericao"],
                nome_posto=nome_posto,
                cfg=cfg,
            )
            _historico.salvar(resultado, caixa_regs, lmc_regs)
            st.session_state["resultado"] = resultado
            st.session_state["origem"] = "upload"

            # Feedback pós-leitura para PDF
            if _lmc_e_pdf and paths["lmc"]:
                # Importa info de extração do PDF (via pdfplumber)
                try:
                    from app.services.pdf_parser import extrair_tabelas_pdf  # noqa: PLC0415
                    _, pdf_info = extrair_tabelas_pdf(paths["lmc"])
                    avisos_pdf = pdf_info.get("avisos", [])
                    paginas_lidas = pdf_info.get("paginas_lidas", 0)
                    paginas_total = pdf_info.get("paginas_total", 0)
                    produtos = pdf_info.get("produtos_encontrados", [])

                    if paginas_total:
                        if paginas_lidas < paginas_total:
                            st.warning(
                                f"⚠️ PDF parcialmente lido: {paginas_lidas} de "
                                f"{paginas_total} página(s) continham tabelas."
                            )
                        else:
                            st.info(
                                f"📄 PDF lido: {paginas_lidas} página(s) processada(s). "
                                f"Produtos encontrados: {', '.join(produtos) if produtos else 'não identificados'}."
                            )
                    for av in avisos_pdf:
                        st.warning(f"⚠️ {av}")
                except Exception:
                    pass  # feedback é opcional — não bloqueia o resultado

        except ValueError as exc:
            msg = str(exc)
            st.error(f"❌ {msg}")
            st.stop()
        except Exception as exc:
            st.error(f"❌ Erro ao processar os arquivos: {exc}")
            st.exception(exc)
            st.stop()

# ---------------------------------------------------------------------------
# Renderização dos resultados
# ---------------------------------------------------------------------------

if "resultado" not in st.session_state:
    st.markdown("---")
    st.markdown(
        "<div style='text-align:center;color:#94a3b8;padding:3rem 0'>"
        "<div style='font-size:3rem'>⛽</div>"
        "<div style='font-size:1.1rem;margin-top:.5rem'>"
        "Envie os arquivos e clique em <strong>ANALISAR DADOS</strong> para iniciar."
        "</div></div>",
        unsafe_allow_html=True,
    )
    st.stop()

resultado: ResultadoAuditoria = st.session_state["resultado"]

st.markdown("---")

# ---------------------------------------------------------------------------
# 1. RESUMO GERAL
# ---------------------------------------------------------------------------

st.markdown("### 📊 Resumo da Auditoria")

divs_lmc   = [d for d in resultado.divergencias if d.tipo == TipoDivergencia.LMC]
divs_caixa = [d for d in resultado.divergencias if d.tipo == TipoDivergencia.CAIXA]
divs_afer  = [d for d in resultado.divergencias if d.tipo == TipoDivergencia.AFERICAO]
divs_ps    = [d for d in resultado.divergencias if d.tipo == TipoDivergencia.PERDA_SOBRA]

criticos = [d for d in resultado.divergencias if d.nivel_risco == NivelRisco.CRITICO]
altos    = [d for d in resultado.divergencias if d.nivel_risco == NivelRisco.ALTO]
medios   = [d for d in resultado.divergencias if d.nivel_risco == NivelRisco.MEDIO]
baixos   = [d for d in resultado.divergencias if d.nivel_risco == NivelRisco.BAIXO]

# Status geral
_status_geral(resultado)
st.markdown("")

# Métricas
c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
with c1: _render_metric("Total de Alertas",   resultado.total_divergencias, "#1e293b")
with c2: _render_metric("LMC",               len(divs_lmc),   "#0ea5e9")
with c3: _render_metric("Caixa",             len(divs_caixa), "#8b5cf6")
with c4: _render_metric("Aferição",          len(divs_afer),  "#f97316")
with c5: _render_metric("Perdas/Sobras",     len(divs_ps),    "#e11d48")
with c6: _render_metric("Críticos + Altos",  len(criticos) + len(altos), "#dc2626")
with c7:
    score = resultado.score_conformidade
    cor_score = "#16a34a" if score >= 80 else "#ca8a04" if score >= 60 else "#dc2626"
    _render_metric("Score", f"{score:.0f}%", cor_score)

st.markdown("")

# ---------------------------------------------------------------------------
# 2. ALERTAS CRÍTICOS
# ---------------------------------------------------------------------------

if criticos or altos:
    with st.expander(
        f"🚨 ALERTAS CRÍTICOS E ALTOS  ({len(criticos) + len(altos)} ocorrências)",
        expanded=True,
    ):
        if not criticos and not altos:
            st.markdown("_Nenhum alerta crítico ou alto._")
        for div in sorted(criticos + altos, key=lambda d: [NivelRisco.CRITICO, NivelRisco.ALTO].index(d.nivel_risco)):
            _render_alerta(div)

# ---------------------------------------------------------------------------
# 3. ALERTAS MÉDIOS
# ---------------------------------------------------------------------------

if medios:
    with st.expander(
        f"⚠️ ALERTAS MÉDIOS  ({len(medios)} ocorrências)",
        expanded=len(criticos) + len(altos) == 0,
    ):
        for div in medios:
            _render_alerta(div)

# ---------------------------------------------------------------------------
# 4. ALERTAS BAIXOS / SEM PROBLEMAS
# ---------------------------------------------------------------------------

if baixos:
    with st.expander(f"ℹ️ OBSERVAÇÕES — BAIXO RISCO  ({len(baixos)} itens)", expanded=False):
        for div in baixos:
            _render_alerta(div)

if not resultado.divergencias:
    st.markdown(
        "<div style='background:#f0fdf4;border:1px solid #86efac;border-radius:10px;"
        "padding:2rem;text-align:center;color:#166534;font-size:1.1rem;font-weight:600'>"
        "✅ Nenhuma divergência encontrada. Operação dentro dos parâmetros normais."
        "</div>",
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# 5. DOWNLOAD DOS RELATÓRIOS
# ---------------------------------------------------------------------------

st.markdown("---")
st.markdown("### 💾 Download dos Relatórios")

col_d1, col_d2, col_d3 = st.columns(3)

with col_d1:
    txt = gerar_relatorio_txt(resultado)
    st.download_button(
        label="📄 Relatório Completo (.txt)",
        data=txt.encode("utf-8"),
        file_name=f"auditoria_{resultado.data_auditoria.strftime('%Y%m%d')}.txt",
        mime="text/plain",
        use_container_width=True,
    )

with col_d2:
    csv = gerar_relatorio_csv(resultado)
    st.download_button(
        label="📊 Divergências (.csv)",
        data=csv.encode("utf-8-sig"),  # BOM para Excel
        file_name=f"divergencias_{resultado.data_auditoria.strftime('%Y%m%d')}.csv",
        mime="text/csv",
        use_container_width=True,
    )

with col_d3:
    json_str = gerar_relatorio_json(resultado)
    st.download_button(
        label="🔗 Dados JSON (.json)",
        data=json_str.encode("utf-8"),
        file_name=f"auditoria_{resultado.data_auditoria.strftime('%Y%m%d')}.json",
        mime="application/json",
        use_container_width=True,
    )

# ---------------------------------------------------------------------------
# 6. ANÁLISE HISTÓRICA
# ---------------------------------------------------------------------------

st.markdown("---")

if _historico.tem_dados():
    import pandas as pd
    try:
        import plotly.express as px
        _plotly_ok = True
    except ImportError:
        _plotly_ok = False

    with st.expander("📊 Análise Histórica", expanded=True):

        # Filtros
        postos_disp = _historico.postos()
        col_f1, col_f2, col_f3 = st.columns([2, 2, 1])
        with col_f1:
            posto_filtro = st.selectbox(
                "Posto", ["Todos"] + postos_disp, key="hist_posto"
            )
        with col_f2:
            periodo = st.selectbox(
                "Período", ["Últimos 7 dias", "Últimos 30 dias",
                            "Últimos 90 dias", "Tudo"],
                index=1, key="hist_periodo"
            )
        _posto = None if posto_filtro == "Todos" else posto_filtro
        _limite = {"Últimos 7 dias": 7, "Últimos 30 dias": 30,
                   "Últimos 90 dias": 90, "Tudo": 9999}[periodo]

        # ── Score ao longo do tempo ────────────────────────────────────
        scores = _historico.scores(posto=_posto, limite=_limite)
        if scores:
            df_score = pd.DataFrame(scores)
            df_score["data"] = pd.to_datetime(df_score["data"])

            st.markdown("#### 📈 Score de Conformidade")
            if _plotly_ok:
                fig = px.line(
                    df_score, x="data", y="score",
                    color="posto" if _posto is None else None,
                    markers=True, range_y=[0, 100],
                    labels={"data": "Data", "score": "Score (%)", "posto": "Posto"},
                )
                fig.add_hline(y=80, line_dash="dash", line_color="#16a34a",
                              annotation_text="Meta 80%")
                fig.add_hline(y=60, line_dash="dash", line_color="#dc2626",
                              annotation_text="Crítico 60%")
                fig.update_layout(height=280, margin=dict(t=10, b=10))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.line_chart(df_score.set_index("data")["score"])

        # ── Diferença de caixa por operador ───────────────────────────
        caixa_hist = _historico.caixa_por_operador(posto=_posto, limite=_limite * 20)
        if caixa_hist:
            df_cx = pd.DataFrame(caixa_hist)
            df_cx["data"] = pd.to_datetime(df_cx["data"])

            st.markdown("#### 💰 Diferença de Caixa por Operador")

            # Gráfico de linha por operador
            if _plotly_ok and len(df_cx["data"].unique()) > 1:
                fig2 = px.line(
                    df_cx, x="data", y="diferenca", color="operador",
                    markers=True,
                    labels={"data": "Data", "diferenca": "Diferença (R$)",
                            "operador": "Operador"},
                )
                fig2.add_hline(y=0, line_color="gray", line_width=1)
                fig2.update_layout(height=300, margin=dict(t=10, b=10))
                st.plotly_chart(fig2, use_container_width=True)

            # Ranking de operadores
            ranking = _historico.ranking_operadores(posto=_posto)
            if ranking:
                st.markdown("**Ranking por divergência acumulada**")
                df_rank = pd.DataFrame(ranking)
                df_rank.columns = ["Operador", "Dias", "Σ Abs (R$)",
                                   "Saldo (R$)", "Média (R$)", "Mín (R$)", "Máx (R$)"]
                df_rank["Σ Abs (R$)"] = df_rank["Σ Abs (R$)"].map("R$ {:.2f}".format)
                df_rank["Saldo (R$)"] = df_rank["Saldo (R$)"].map("{:+.2f}".format)
                df_rank["Média (R$)"] = df_rank["Média (R$)"].map("{:+.2f}".format)
                st.dataframe(df_rank, use_container_width=True, hide_index=True)

        # ── Perdas/Sobras LMC por produto ─────────────────────────────
        lmc_hist = _historico.lmc_por_tanque(posto=_posto, limite=_limite * 20)
        lmc_hist_filt = [r for r in lmc_hist if r["perdas_sobras"] != 0]
        if lmc_hist_filt:
            df_lmc = pd.DataFrame(lmc_hist_filt)
            df_lmc["data"] = pd.to_datetime(df_lmc["data"])

            st.markdown("#### 📦 Perdas e Sobras por Produto (LMC)")

            if _plotly_ok and len(df_lmc["data"].unique()) > 1:
                fig3 = px.bar(
                    df_lmc, x="data", y="perdas_sobras", color="tanque",
                    barmode="group",
                    labels={"data": "Data", "perdas_sobras": "Perda/Sobra (L)",
                            "tanque": "Produto"},
                )
                fig3.add_hline(y=0, line_color="gray", line_width=1)
                fig3.update_layout(height=300, margin=dict(t=10, b=10))
                st.plotly_chart(fig3, use_container_width=True)

            ranking_t = _historico.ranking_tanques(posto=_posto)
            if ranking_t:
                st.markdown("**Ranking por perda total acumulada**")
                df_rt = pd.DataFrame(ranking_t)
                df_rt.columns = ["Produto/Tanque", "Dias", "Perda Total (L)", "Média/Dia (L)"]
                df_rt["Perda Total (L)"] = df_rt["Perda Total (L)"].map("{:+.1f}".format)
                df_rt["Média/Dia (L)"] = df_rt["Média/Dia (L)"].map("{:+.2f}".format)
                st.dataframe(df_rt, use_container_width=True, hide_index=True)

        if not scores and not caixa_hist and not lmc_hist_filt:
            st.info("Nenhum dado histórico disponível para os filtros selecionados.")

# ---------------------------------------------------------------------------
# Rodapé
# ---------------------------------------------------------------------------

st.markdown("---")
st.markdown(
    "<div style='text-align:center;color:#94a3b8;font-size:0.8rem'>"
    "Sistema de Auditoria Operacional · Todos os cálculos são determinísticos · "
    f"Posto: <strong>{resultado.posto}</strong> · "
    f"Data: <strong>{resultado.data_auditoria.strftime('%d/%m/%Y')}</strong>"
    "</div>",
    unsafe_allow_html=True,
)
