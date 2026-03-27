import streamlit as st
import math
import pandas as pd
import datetime
import os
import io
from fpdf import FPDF
from cryptography.fernet import Fernet
import base64

# ==========================================
# CONFIGURAÇÃO DE SEGURANÇA (CRIPTOGRAFIA)
# ==========================================
# Chave mestra para criptografia (Em um sistema real, essa chave ficaria em um cofre de senhas)
# Aqui, geramos uma chave baseada em uma frase fixa para manter a consistência dos arquivos
def gerar_chave(senha_mestra):
    hash_senha = base64.urlsafe_b64encode(senha_mestra.ljust(32)[:32].encode())
    return hash_senha

SENHA_ADMIN = "HUGV2026"  # <--- Altere sua senha aqui
CHAVE_CRIPTOGRAFIA = gerar_chave("HarveyCushingHUGVManaus")
fernet = Fernet(CHAVE_CRIPTOGRAFIA)

ARQUIVO_DADOS = "dados_protegidos.dat"

def salvar_dados_criptografados(df):
    csv_str = df.to_csv(index=False)
    dados_cripto = fernet.encrypt(csv_str.encode())
    with open(ARQUIVO_DADOS, "wb") as f:
        f.write(dados_cripto)

def carregar_dados_descriptografados():
    if not os.path.exists(ARQUIVO_DADOS):
        return pd.DataFrame(columns=["Data/Hora", "Prontuário", "Paciente", "Mãe", "Avaliação Clínica", "Resultado (%)", "Classificação", "Tipo"])
    
    with open(ARQUIVO_DADOS, "rb") as f:
        dados_cripto = f.read()
    
    try:
        dados_puro = fernet.decrypt(dados_cripto).decode()
        return pd.read_csv(io.StringIO(dados_puro), dtype={'Prontuário': str})
    except:
        return pd.DataFrame(columns=["Data/Hora", "Prontuário", "Paciente", "Mãe", "Avaliação Clínica", "Resultado (%)", "Classificação", "Tipo"])

# ==========================================
# CONFIGURAÇÃO INICIAL E ESTADO DA SESSÃO
# ==========================================
st.set_page_config(page_title="NeuroPreditor Harvey", layout="wide", page_icon="🧠")

if 'autenticado' not in st.session_state:
    st.session_state.autenticado = False
if 'paciente_ativo' not in st.session_state:
    st.session_state.paciente_ativo = {"nome": "", "mae": "", "prontuario": ""}
if 'ultimo_resultado' not in st.session_state:
    st.session_state.ultimo_resultado = None

# ==========================================
# TELA DE LOGIN (LGPD)
# ==========================================
if not st.session_state.autenticado:
    st.markdown("<h1 class='main-title'>NeuroPreditor <span class='harvey-text'>Harvey</span></h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align:center;'>Acesso Restrito - Unidade de Neurocirurgia HUGV/UFAM</p>", unsafe_allow_html=True)
    
    with st.container():
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            st.markdown("<div class='input-card'>", unsafe_allow_html=True)
            senha_input = st.text_input("Digite a senha de acesso:", type="password")
            if st.button("Entrar no Sistema"):
                if senha_input == SENHA_ADMIN:
                    st.session_state.autenticado = True
                    st.rerun()
                else:
                    st.error("Senha incorreta. Acesso negado.")
            st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

# ==========================================
# FUNÇÕES DE CÁLCULO (BACK-END)
# ==========================================
def risco_pdh_cai_2023(teve_hiponatremia_pod1_2, monocitos_perc, pt_segundos):
    beta_hypo, beta_mono, beta_pt, beta_0 = 0.97, 0.20, 0.58, -12.50 
    x_hypo = 1 if teve_hiponatremia_pod1_2 else 0
    logit = beta_0 + (beta_hypo * x_hypo) + (beta_mono * monocitos_perc) + (beta_pt * pt_segundos)
    return (1 / (1 + math.exp(-logit))) * 100

def risco_pdh_tan_2025(prl_pre_op, elevacao_diafragma_mm, teve_hiponatremia_d1_d2):
    beta_prl, beta_elevacao, beta_hipo_precoce, beta_0 = 0.00995, 0.501, 3.486, -7.50 
    x_hipo_precoce = 1 if teve_hiponatremia_d1_d2 else 0
    logit = beta_0 + (beta_prl * prl_pre_op) + (beta_elevacao * elevacao_diafragma_mm) + (beta_hipo_precoce * x_hipo_precoce)
    return (1 / (1 + math.exp(-logit))) * 100

def risco_fistula_lcr_zhang_2025(kelly_maior_igual_2, suprasselar_maior_igual_B, pneumoencefalo_maior_igual_3, tamanho_janela_ossea_mm):
    beta_kelly, beta_supra, beta_pneumo, beta_janela, beta_0 = 1.55, 1.77, 2.56, 0.18, -10.00 
    x_kelly, x_supra, x_pneumo = (1 if kelly_maior_igual_2 else 0), (1 if suprasselar_maior_igual_B else 0), (1 if pneumoencefalo_maior_igual_3 else 0)
    logit = beta_0 + (beta_kelly * x_kelly) + (beta_supra * x_supra) + (beta_pneumo * x_pneumo) + (beta_janela * tamanho_janela_ossea_mm)
    return (1 / (1 + math.exp(-logit))) * 100

def risco_diabetes_insipidus_li_2024(tem_diabetes, tem_hipertensao, tem_cardiopatia, cortisol_pre_op, teve_fistula_pos_op, textura_tumor_rigida):
    beta_diabetes, beta_hipertensao, beta_cardiopatia = 0.845, 0.672, 1.039
    beta_cortisol, beta_fistula, beta_textura, beta_0 = 0.001, 1.121, 0.776, -6.50 
    x_d, x_h, x_c, x_f, x_t = (1 if tem_diabetes else 0), (1 if tem_hipertensao else 0), (1 if tem_cardiopatia else 0), (1 if teve_fistula_pos_op else 0), (1 if textura_tumor_rigida else 0)
    logit = beta_0 + (beta_diabetes * x_d) + (beta_hipertensao * x_h) + (beta_cardiopatia * x_c) + (beta_cortisol * cortisol_pre_op) + (beta_fistula * x_f) + (beta_textura * x_t)
    return (1 / (1 + math.exp(-logit))) * 100

def risco_melhora_visual_ji_2023(compressao_quiasma, defeito_difuso, duracao_sintomas_meses, md_pre_operatorio):
    pontos_totais = 0
    if compressao_quiasma: pontos_totais += 13
    if defeito_difuso: pontos_totais += 20
    pontos_totais += max(0, 100 - (2.5 * duracao_sintomas_meses))
    pontos_totais += max(0, (md_pre_operatorio - 2) * (20.0 / 14.0))
    return min(95.0, max(5.0, (pontos_totais / 103.0) * 33.0))

def risco_recorrencia_cushing_cuper_2025(duracao_sintomas_meses, hardy_grade, localizacao_tumor, cirurgia_previa):
    pontos_totais = (min(240.0, max(0.0, duracao_sintomas_meses)) * (100.0 / 240.0)) + (min(4, max(0, hardy_grade)) * 12.5)
    loc = local_tumor.lower()
    pontos_totais += 14 if loc == 'direita' else 18 if loc == 'central' else 22 if loc == 'esquerda' else 33 if loc in ['haste', 'stalk'] else 0
    if cirurgia_previa: pontos_totais += 28
    if pontos_totais <= 60: prob = (pontos_totais / 60.0) * 10.0
    elif pontos_totais <= 100: prob = 10.0 + ((pontos_totais - 60.0) / 40.0) * 30.0
    elif pontos_totais <= 120: prob = 40.0 + ((pontos_totais - 100.0) / 20.0) * 25.0
    else: prob = 65.0 + ((pontos_totais - 120.0) / 20.0) * 20.0
    return min(95.0, max(1.0, prob))

def risco_meningite_zhou_2025(duracao_cirurgia_h, diametro_tumor_cm, fistula_intraop):
    beta_duracao, beta_diametro, beta_fistula, beta_0 = 0.98, 0.99, 2.22, -8.00 
    x_f = 1 if fistula_intraop else 0
    logit = beta_0 + (beta_duracao * duracao_cirurgia_h) + (beta_diametro * diametro_tumor_cm) + (beta_fistula * x_f)
    return (1 / (1 + math.exp(-logit))) * 100

# ==========================================
# GESTÃO DE DADOS (LOG LGPD)
# ==========================================
def obter_classificacao(probabilidade, tipo="risco"):
    if tipo == "melhora":
        return ("Alta Chance", "green") if probabilidade >= 60 else ("Chance Moderada", "orange") if probabilidade >= 30 else ("Baixa Chance", "red")
    return ("Baixo Risco", "green") if probabilidade < 20 else ("Risco Moderado", "orange") if probabilidade < 45 else ("Alto Risco", "red")

def salvar_registro(modulo_analise, probabilidade, tipo="risco"):
    df = carregar_dados_descriptografados()
    classificacao, _ = obter_classificacao(probabilidade, tipo)
    data_hora = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    
    novo_dado = pd.DataFrame([{
        "Data/Hora": data_hora, "Prontuário": str(st.session_state.paciente_ativo['prontuario']),
        "Paciente": st.session_state.paciente_ativo['nome'], "Mãe": st.session_state.paciente_ativo['mae'],
        "Avaliação Clínica": modulo_analise, "Resultado (%)": round(probabilidade, 1),
        "Classificação": classificacao, "Tipo": tipo
    }])
    
    df_final = pd.concat([df, novo_dado], ignore_index=True)
    salvar_dados_criptografados(df_final)
    return True

# ==========================================
# ESTILOS CSS
# ==========================================
st.markdown("""
<style>
    body { background-color: #f4f7f6; }
    .main-title { background: -webkit-linear-gradient(45deg, #0b2e59, #1565c0); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-weight: 900; font-size: 3.2rem; margin-bottom: 0; text-align: center; }
    .harvey-text { font-family: 'Georgia', serif; font-style: italic; background: -webkit-linear-gradient(45deg, #b8860b, #ffd700); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-weight: normal; margin-left: 10px; }
    .patient-header { background: linear-gradient(135deg, #0b2e59, #1565c0); color: white; padding: 20px 30px; border-radius: 12px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center;}
    .dashboard-card { background-color: white; border-radius: 15px; padding: 20px; box-shadow: 0 4px 12px rgba(0,0,0,0.08); text-align: center; border-top: 6px solid #ddd; height: 100%; transition: transform 0.2s; }
    .card-value { font-size: 2.5rem; font-weight: 800; margin: 5px 0; }
    .b-green { border-top-color: #2e7d32 !important; } .t-green { color: #2e7d32 !important; }
    .b-orange { border-top-color: #ef6c00 !important; } .t-orange { color: #ef6c00 !important; }
    .b-red { border-top-color: #c62828 !important; } .t-red { color: #c62828 !important; }
    .input-card { background-color: #ffffff; padding: 25px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.04); margin-top: 15px; border: 1px solid #e0e0e0; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# BARRA LATERAL
# ==========================================
with st.sidebar:
    st.markdown("<div style='text-align: center;'>", unsafe_allow_html=True)
    st.markdown("<h4 style='color: #0b2e59; margin-top: 5px;'>HUGV - UFAM</h4>", unsafe_allow_html=True)
    st.markdown("<h2 style='color: #0b2e59; margin-top: 15px;'>NeuroPreditor <span class='harvey-text'>Harvey</span></h2>", unsafe_allow_html=True)
    st.markdown("<p style='color: #888; font-size: 0.8rem;'>Protocolo Seguro LGPD</p></div>", unsafe_allow_html=True)
    st.markdown("---")
    nav = st.radio("Menu Principal:", ["🏠 Área de Trabalho", "⚙️ Gerenciar Banco de Dados"])
    if st.session_state.paciente_ativo['prontuario']:
        st.markdown("---")
        st.button("❌ Encerrar Prontuário", on_click=deslogar, type="primary")

# ==========================================
# ÁREA DE TRABALHO (ACESSAR/CADASTRAR)
# ==========================================
if not st.session_state.paciente_ativo['prontuario'] and nav == "🏠 Área de Trabalho":
    st.markdown("<h1 class='main-title'>NeuroPreditor Transesfenoidal <span class='harvey-text'>Harvey</span></h1>", unsafe_allow_html=True)
    st.markdown("<div style='max-width: 900px; margin: 0 auto 35px auto; padding: 25px; background:#fff; border-left:6px solid #b8860b; border-radius:12px; box-shadow:0 4px 15px rgba(0,0,0,0.06); text-align: center;'><p style='font-size:1.35rem; font-style:italic;'>\"Gostaria de ver o dia em que alguém fosse nomeado cirurgião sem ter mãos, pois a parte operatória é a menor parte do trabalho.\"</p><p style='color:#b8860b; font-weight:800;'>— HARVEY WILLIAMS CUSHING</p></div>", unsafe_allow_html=True)
    
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("<div class='input-card'><h3>🔍 Acessar Prontuário Antigo</h3>", unsafe_allow_html=True)
        df_busca = carregar_dados_descriptografados()
        if not df_busca.empty:
            lista_pac = df_busca.drop_duplicates(subset=['Prontuário'])
            escolha = st.selectbox("Selecione o paciente:", [""] + [f"{r['Prontuário']} - {r['Paciente']}" for _, r in lista_pac.iterrows()])
            if st.button("Abrir Prontuário") and escolha:
                bp = escolha.split(" - ")[0]
                pdf_data = df_busca[df_busca['Prontuário'] == str(bp)]
                st.session_state.paciente_ativo = {"prontuario": str(bp), "nome": pdf_data.iloc[0]['Paciente'], "mae": pdf_data.iloc[0]['Mãe']}
                st.rerun()
        else: st.info("Nenhum paciente no sistema.")
        st.markdown("</div>", unsafe_allow_html=True)
    with c2:
        st.markdown("<div class='input-card'><h3>➕ Novo Paciente</h3>", unsafe_allow_html=True)
        nn, nm, np = st.text_input("Nome:"), st.text_input("Mãe:"), st.text_input("Nº Prontuário:")
        if st.button("Cadastrar Paciente"):
            if nn and np:
                st.session_state.paciente_ativo = {"nome": nn, "mae": nm, "prontuario": str(np)}
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

# ==========================================
# INTERFACE DO PRONTUÁRIO ATIVO
# ==========================================
if nav == "🏠 Área de Trabalho" and st.session_state.paciente_ativo['prontuario']:
    st.markdown(f'<div class="patient-header"><div><p style="font-size:0.8rem;opacity:0.8;">PRONTUÁRIO ATIVO</p><h2>👤 {st.session_state.paciente_ativo["nome"]}</h2></div><div><p>Prontuário: {st.session_state.paciente_ativo["prontuario"]}</p></div></div>', unsafe_allow_html=True)
    tabs = st.tabs(["📊 Painel", "👁️ Visão", "🔄 Cushing", "💧 Fístula", "🚰 D.I.", "🧂 Hiponatremia", "🦠 Meningite"])

    with tabs[0]: # PAINEL
        df_pac = carregar_dados_descriptografados()
        df_pac = df_pac[df_pac['Prontuário'] == str(st.session_state.paciente_ativo['prontuario'])]
        if not df_pac.empty:
            df_l = df_pac.sort_values(by="Data/Hora").groupby("Avaliação Clínica").last().reset_index()
            cols = st.columns(3)
            for i, r in df_l.iterrows():
                v = float(r['Resultado (%)'])
                l, c = obter_classificacao(v, r['Tipo'])
                with cols[i % 3]:
                    st.markdown(f'<div class="dashboard-card b-{c}"><div style="font-weight:bold;color:#555;">{r["Avaliação Clínica"]}</div><div class="card-value t-{c}">{v}%</div><div style="font-weight:bold;" class="t-{c}">{l}</div><div style="font-size:0.7rem;color:#aaa;">{r["Data/Hora"]}</div></div><br>', unsafe_allow_html=True)
        else: st.info("Sem cálculos arquivados.")

    # CALCULADORAS (Simplificadas para manter o código direto)
    with tabs[1]: # VISÃO
        st.markdown("<div class='input-card'>", unsafe_allow_html=True)
        v_q, v_d = st.toggle("Compressão quiasma?", help="RM Coronal"), st.toggle("Defeito difuso?")
        v_m, v_md = st.number_input("Meses sintomas:", 0), st.number_input("MD (dB) pré-op:", 0.0)
        if st.button("Calcular e Salvar Visão"):
            res = risco_melhora_visual_ji_2023(v_q, v_d, v_m, v_md)
            st.session_state.ultimo_resultado = {"m": "Prognóstico Visual", "v": res, "t": "melhora"}
            salvar_registro("Prognóstico Visual", res, "melhora"); st.rerun()
        if st.session_state.ultimo_resultado and st.session_state.ultimo_resultado['m'] == "Prognóstico Visual":
            st.metric("Resultado", f"{st.session_state.ultimo_resultado['v']:.1f}%")
        st.markdown("</div>", unsafe_allow_html=True)

    with tabs[3]: # FÍSTULA
        st.markdown("<div class='input-card'>", unsafe_allow_html=True)
        f_k, f_s = st.toggle("Kelly ≥ 2?"), st.toggle("Suprasselar ≥ B?")
        f_p, f_j = st.toggle("Pneumoencéfalo ≥ 3?"), st.number_input("Janela (mm):", 0.0)
        if st.button("Calcular e Salvar Fístula"):
            res = risco_fistula_lcr_zhang_2025(f_k, f_s, f_p, f_j)
            st.session_state.ultimo_resultado = {"m": "Risco Fístula LCR", "v": res, "t": "risco"}
            salvar_registro("Risco Fístula LCR", res, "risco"); st.rerun()
        if st.session_state.ultimo_resultado and st.session_state.ultimo_resultado['m'] == "Risco Fístula LCR":
            st.metric("Risco", f"{st.session_state.ultimo_resultado['v']:.1f}%")
        st.markdown("</div>", unsafe_allow_html=True)

# ==========================================
# GERENCIAMENTO (ZONA DE EXCLUSÃO)
# ==========================================
elif nav == "⚙️ Gerenciar Banco de Dados":
    st.title("⚙️ Gerenciamento Seguro (LGPD)")
    df_g = carregar_dados_descriptografados()
    if not df_g.empty:
        st.dataframe(df_g, use_container_width=True, hide_index=True)
        st.markdown("---")
        lista_del = df_g.drop_duplicates(subset=['Prontuário'])
        p_del = st.selectbox("Excluir Paciente permanentemente:", [""] + [f"{r['Prontuário']} - {r['Paciente']}" for _, r in lista_del.iterrows()])
        if st.button("🚨 CONFIRMAR EXCLUSÃO PERMANENTE") and p_del:
            id_del = p_del.split(" - ")[0]
            df_nova = df_g[df_g['Prontuário'] != id_del]
            salvar_dados_criptografados(df_nova)
            st.success("Dados removidos conforme a LGPD.")
            st.rerun()
    else: st.info("Banco de dados vazio.")
