import streamlit as st
import math
import pandas as pd
import datetime
import os

# ==========================================
# CONFIGURAÇÃO INICIAL E ESTADO DA SESSÃO
# ==========================================
st.set_page_config(page_title="NeuroPreditor Harvey", layout="wide", page_icon="🧠")

if 'paciente_ativo' not in st.session_state:
    st.session_state.paciente_ativo = {"nome": "", "mae": "", "prontuario": ""}

ARQUIVO_CSV = "registro_pacientes.csv"

# ==========================================
# LÓGICA DE APOIO À DECISÃO (TRAFFIC LIGHT)
# ==========================================
def obter_conduta_sugerida(modulo, prob, tipo):
    if modulo == "Prognóstico Visual":
        if prob >= 60: return "green", "Ótimo prognóstico. Manter plano cirúrgico e alinhar alta expectativa de recuperação visual."
        elif prob >= 30: return "yellow", "Prognóstico moderado. Alinhar com o paciente que a recuperação pode ser parcial ou lenta."
        else: return "red", "Baixa probabilidade de melhora. Alinhamento rigoroso de expectativas no pré-op."
    elif modulo == "Recorrência Cushing":
        if prob < 20: return "green", "Baixo risco de recorrência. Seguir protocolo padrão de seguimento."
        elif prob < 45: return "yellow", "Risco moderado. Vigilância apertada de cortisol urinário/salivar no 1º ano."
        else: return "red", "Alto risco. Considerar RM precoce e avaliação multidisciplinar para terapias adjuvantes."
    elif modulo == "Risco Fístula LCR":
        if prob < 10: return "green", "Baixo risco. Técnica de fechamento padrão costuma ser suficiente."
        elif prob < 20: return "yellow", "Risco moderado. Reforçar reconstrução e considerar repouso absoluto."
        else: return "red", "ALTO RISCO. Considerar Flap Nasoseptal e avaliação de Dreno Lombar profilático."
    elif modulo == "Diabetes Insipidus":
        if prob < 15: return "green", "Baixo risco. Monitorização padrão de balanço hídrico."
        elif prob < 35: return "yellow", "Risco moderado. Vigilância estrita de densidade urinária e eletrólitos."
        else: return "red", "Alto risco. Protocolo rigoroso; ter Desmopressina (DDAVP) disponível."
    elif "DPH" in modulo:
        if prob < 15: return "green", "Baixo risco. Alta segura com orientações padrão."
        elif prob < 30: return "yellow", "Risco moderado. Orientar restrição hídrica leve e sódio no 7º POD."
        else: return "red", "ALTO RISCO. Adiar alta ou garantir coleta de sódio em 48h; orientar sinais de alerta."
    return "gray", ""

# ==========================================
# FUNÇÕES DE CÁLCULO (BACK-END)
# ==========================================
def risco_pdh_cai_2023(teve_hiponatremia_pod1_2, monocitos_perc, pt_segundos):
    beta_hypo, beta_mono, beta_pt = 0.97, 0.20, 0.58
    beta_0 = -12.50 
    x_hypo = 1 if teve_hiponatremia_pod1_2 else 0
    logit = beta_0 + (beta_hypo * x_hypo) + (beta_mono * monocitos_perc) + (beta_pt * pt_segundos)
    return (1 / (1 + math.exp(-logit))) * 100

def risco_pdh_tan_2025(prl_pre_op, elevacao_diafragma_mm, teve_hiponatremia_d1_d2):
    beta_prl, beta_elevacao, beta_hipo_precoce = 0.00995, 0.501, 3.486
    beta_0 = -7.50 
    x_hipo_precoce = 1 if teve_hiponatremia_d1_d2 else 0
    logit = beta_0 + (beta_prl * prl_pre_op) + (beta_elevacao * elevacao_diafragma_mm) + (beta_hipo_precoce * x_hipo_precoce)
    return (1 / (1 + math.exp(-logit))) * 100

def risco_fistula_lcr_zhang_2025(kelly_maior_igual_2, suprasselar_maior_igual_B, pneumoencefalo_maior_igual_3, tamanho_janela_ossea_mm):
    beta_kelly, beta_supra, beta_pneumo, beta_janela = 1.55, 1.77, 2.56, 0.18
    beta_0 = -10.00 
    x_kelly = 1 if kelly_maior_igual_2 else 0
    x_supra = 1 if suprasselar_maior_igual_B else 0
    x_pneumo = 1 if pneumoencefalo_maior_igual_3 else 0
    logit = beta_0 + (beta_kelly * x_kelly) + (beta_supra * x_supra) + (beta_pneumo * x_pneumo) + (beta_janela * tamanho_janela_ossea_mm)
    return (1 / (1 + math.exp(-logit))) * 100

def risco_diabetes_insipidus_li_2024(tem_diabetes, tem_hipertensao, tem_cardiopatia, cortisol_pre_op, teve_fistula_pos_op, textura_tumor_rigida):
    beta_diabetes, beta_hipertensao, beta_cardiopatia = 0.845, 0.672, 1.039
    beta_cortisol, beta_fistula, beta_textura = 0.001, 1.121, 0.776
    beta_0 = -6.50 
    x_diabetes = 1 if tem_diabetes else 0
    x_hipertensao = 1 if tem_hipertensao else 0
    x_cardiopatia = 1 if tem_cardiopatia else 0
    x_fistula = 1 if teve_fistula_pos_op else 0
    x_textura = 1 if textura_tumor_rigida else 0
    logit = beta_0 + (beta_diabetes * x_diabetes) + (beta_hipertensao * x_hipertensao) + \
            (beta_cardiopatia * x_cardiopatia) + (beta_cortisol * cortisol_pre_op) + \
            (beta_fistula * x_fistula) + (beta_textura * x_textura)
    return (1 / (1 + math.exp(-logit))) * 100

def risco_melhora_visual_ji_2023(compressao_quiasma, defeito_difuso, duracao_sintomas_meses, md_pre_operatorio):
    pontos_totais = 0
    if compressao_quiasma: pontos_totais += 13
    if defeito_difuso: pontos_totais += 20
    pontos_totais += max(0, 100 - (2.5 * duracao_sintomas_meses))
    pontos_totais += max(0, (md_pre_operatorio - 2) * (20.0 / 14.0))
    probabilidade = (pontos_totais / 103.0) * 33.0 
    return min(90.0, max(5.0, probabilidade))

def risco_recorrencia_cushing_cuper_2025(duracao_sintomas_meses, hardy_grade, localizacao_tumor, cirurgia_previa):
    pontos_totais = 0
    pontos_totais += min(240.0, max(0.0, duracao_sintomas_meses)) * (100.0 / 240.0)
    pontos_totais += min(4, max(0, hardy_grade)) * 12.5
    loc = localizacao_tumor.lower()
    if loc == 'direita': pontos_totais += 14
    elif loc == 'central': pontos_totais += 18
    elif loc == 'esquerda': pontos_totais += 22
    elif loc in ['haste', 'stalk']: pontos_totais += 33
    if cirurgia_previa: pontos_totais += 28
    
    if pontos_totais <= 60: prob = (pontos_totais / 60.0) * 10.0
    elif pontos_totais <= 100: prob = 10.0 + ((pontos_totais - 60.0) / 40.0) * 30.0
    elif pontos_totais <= 120: prob = 40.0 + ((pontos_totais - 100.0) / 20.0) * 25.0
    else: prob = 65.0 + ((pontos_totais - 120.0) / 20.0) * 20.0
    return min(95.0, max(1.0, prob))

# ==========================================
# GESTÃO DE DADOS
# ==========================================
def salvar_registro(paciente, mae, prontuario, modulo_analise, probabilidade, tipo="risco"):
    data_hora = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    _, conduta = obter_conduta_sugerida(modulo_analise, probabilidade, tipo)
    novo_dado = pd.DataFrame([{"Data/Hora": data_hora, "Prontuário": prontuario, "Paciente": paciente, "Mãe": mae, "Avaliação Clínica": modulo_analise, "Resultado (%)": round(probabilidade, 1), "Tipo": tipo, "Recomendação": conduta}])
    if os.path.exists(ARQUIVO_CSV):
        df = pd.read_csv(ARQUIVO_CSV)
        df = pd.concat([df, novo_dado], ignore_index=True)
    else: df = novo_dado
    df.to_csv(ARQUIVO_CSV, index=False)

# ==========================================
# ESTILOS CSS
# ==========================================
st.markdown("""
<style>
    body { background-color: #f4f7f6; }
    .main-title { background: -webkit-linear-gradient(45deg, #0b2e59, #1565c0); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-weight: 900; font-size: 3.2rem; margin-bottom: 0; text-align: center; }
    .harvey-text { font-family: 'Georgia', serif; font-style: italic; background: -webkit-linear-gradient(45deg, #b8860b, #ffd700); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-weight: normal; margin-left: 10px; }
    .patient-header { background: linear-gradient(135deg, #0b2e59, #1565c0); color: white; padding: 20px 30px; border-radius: 12px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center;}
    .dashboard-card { background-color: white; border-radius: 12px; padding: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); text-align: center; border-bottom: 5px solid #ddd; height: 100%; }
    .border-green { border-bottom-color: #2e7d32 !important; } .text-green { color: #2e7d32 !important; }
    .border-yellow { border-bottom-color: #fbc02d !important; } .text-yellow { color: #fbc02d !important; }
    .border-red { border-bottom-color: #c62828 !important; } .text-red { color: #c62828 !important; }
    .input-card { background-color: #ffffff; padding: 25px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.04); margin-top: 15px; border: 1px solid #e0e0e0; }
    .conduta-box { font-size: 0.85rem; background: #f8f9fa; padding: 10px; border-radius: 5px; border: 1px dashed #ccc; margin-top: 10px; text-align: left; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# BARRA LATERAL
# ==========================================
def deslogar_paciente():
    st.session_state.paciente_ativo = {"nome": "", "mae": "", "prontuario": ""}

with st.sidebar:
    st.markdown("<div style='text-align: center;'>", unsafe_allow_html=True)
    st.markdown("<h4 style='color: #0b2e59; margin-top: 5px;'>HUGV - UFAM</h4>", unsafe_allow_html=True)
    st.markdown("<h2 style='color: #0b2e59; margin-top: 15px;'>NeuroPreditor <span style='font-family: Georgia; font-style: italic; color: #b8860b;'>Harvey</span></h2>", unsafe_allow_html=True)
    st.markdown("<p style='color: #888; font-size: 0.8rem;'>Made by Vinícius Bacelar Ferreira</p></div>", unsafe_allow_html=True)
    st.markdown("---")
    nav = st.radio("Menu:", ["🏠 Área de Trabalho", "⚙️ Banco de Dados Geral"])
    if st.session_state.paciente_ativo['prontuario']:
        st.button("❌ Fechar Prontuário", on_click=deslogar_paciente, type="primary")

# ==========================================
# HOME PAGE
# ==========================================
if not st.session_state.paciente_ativo['prontuario'] and nav == "🏠 Área de Trabalho":
    st.markdown("<h1 class='main-title'>NeuroPreditor Transesfenoidal <span class='harvey-text'>Harvey</span></h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #888;'><em>Made by Vinícius Bacelar Ferreira</em></p>", unsafe_allow_html=True)
    
    st.markdown("""
    <div style='max-width: 900px; margin: 0 auto 35px auto; padding: 25px; background:#fff; border-left:6px solid #b8860b; border-radius:12px; box-shadow:0 4px 15px rgba(0,0,0,0.06); text-align: center;'>
        <p style='font-size:1.35rem; font-style:italic; line-height: 1.6;'>\"Gostaria de ver o dia em que alguém fosse nomeado cirurgião sem ter mãos, pois a parte operatória é a menor parte do trabalho.\"</p>
        <p style='color:#b8860b; font-weight:800; letter-spacing: 1px;'>— HARVEY WILLIAMS CUSHING</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("<div class='input-card'><h3>🔍 Acessar Prontuário</h3>", unsafe_allow_html=True)
        bp = st.text_input("Nº Prontuário:")
        if st.button("Abrir"):
            if os.path.exists(ARQUIVO_CSV):
                df = pd.read_csv(ARQUIVO_CSV)
                pdf = df[df['Prontuário'].astype(str) == str(bp)]
                if not pdf.empty:
                    st.session_state.paciente_ativo = {"prontuario": bp, "nome": pdf.iloc[0]['Paciente'], "mae": pdf.iloc[0]['Mãe']}
                    st.rerun()
            st.error("Não encontrado.")
        st.markdown("</div>", unsafe_allow_html=True)
    with c2:
        st.markdown("<div class='input-card'><h3>➕ Novo Paciente</h3>", unsafe_allow_html=True)
        nn, nm, np = st.text_input("Nome:"), st.text_input("Mãe:"), st.text_input("Prontuário:")
        if st.button("Registrar"):
            if nn and np:
                st.session_state.paciente_ativo = {"nome": nn, "mae": nm, "prontuario": np}
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

# ==========================================
# PRONTUÁRIO ABERTO
# ==========================================
if nav == "🏠 Área de Trabalho" and st.session_state.paciente_ativo['prontuario']:
    st.markdown(f'<div class="patient-header"><div><p style="font-size:0.8rem;opacity:0.8;">HUGV - PRONTUÁRIO ABERTO</p><h2>👤 {st.session_state.paciente_ativo["nome"]}</h2></div><div><p>Prontuário: {st.session_state.paciente_ativo["prontuario"]}</p></div></div>', unsafe_allow_html=True)
    t1, t2, t3, t4, t5, t6 = st.tabs(["📊 Resumo e Condutas", "👁️ Visão", "🔄 Cushing", "💧 Fístula", "🚰 Diabetes Insipidus", "🧂 Hiponatremia"])

    with t1:
        st.subheader("💡 Painel de Inteligência Clínica")
        if os.path.exists(ARQUIVO_CSV):
            df = pd.read_csv(ARQUIVO_CSV)
            dp = df[df['Prontuário'].astype(str) == str(st.session_state.paciente_ativo['prontuario'])]
            if not dp.empty:
                dl = dp.sort_values('Data/Hora').groupby('Avaliação Clínica').tail(1)
                cols = st.columns(3)
                for i, (_, row) in enumerate(dl.iterrows()):
                    cor, conduta = obter_conduta_sugerida(row['Avaliação Clínica'], row['Resultado (%)'], row['Tipo'])
                    with cols[i % 3]:
                        st.markdown(f'<div class="dashboard-card border-{cor}"><h4 style="margin-bottom:0;">{row["Avaliação Clínica"]}</h4><div class="value text-{cor}">{row["Resultado (%)"]}%</div><div class="conduta-box"><strong>💡 Recomendação:</strong><br>{conduta}</div><p style="font-size:0.7rem;color:#999;margin-top:10px;">{row["Data/Hora"]}</p></div><br>', unsafe_allow_html=True)
            else: st.info("Realize as avaliações nas abas acima.")

    with t2:
        st.markdown("<div class='input-card'><h4>👁️ Recuperação Visual (Pré-op)</h4>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1: q, d = st.toggle("Compressão quiasma?"), st.toggle("Defeito difuso?")
        with c2: m, md = st.number_input("Meses sintomas:", 0), st.number_input("MD (dB):", 0.0)
        if st.button("Calcular e Salvar Visão"):
            res = risco_melhora_visual_ji_2023(q, d, m, md)
            st.metric("Chance de Melhora", f"{res:.1f}%")
            salvar_registro(st.session_state.paciente_ativo['nome'], st.session_state.paciente_ativo['mae'], st.session_state.paciente_ativo['prontuario'], "Prognóstico Visual", res, "melhora")
        with st.expander("📚 Referência"): st.markdown("Ji X, et al. *Front Oncol*. 2023. DOI: 10.3389/fonc.2023.1108883")
        st.markdown("</div>", unsafe_allow_html=True)

    with t3:
        st.markdown("<div class='input-card'><h4>🔄 Recorrência Cushing</h4>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1: m, cp = st.number_input("Meses sintomas:", 0, key="cush_m"), st.toggle("Cirurgia prévia?")
        with c2: h, l = st.select_slider("Hardy:", [0,1,2,3,4]), st.selectbox("Local:", ["Bilateral","Direita","Esquerda","Central","Haste"])
        if st.button("Calcular e Salvar Cushing"):
            res = risco_recorrencia_cushing_cuper_2025(m, h, l, cp)
            st.metric("Risco de Recorrência", f"{res:.1f}%")
            salvar_registro(st.session_state.paciente_ativo['nome'], st.session_state.paciente_ativo['mae'], st.session_state.paciente_ativo['prontuario'], "Recorrência Cushing", res, "risco")
        with st.expander("📚 Referência"): st.markdown("Sharifi G, et al. *J Clin Transl Endocrinol*. 2025. DOI: 10.1016/j.jcte.2025.100417")
        st.markdown("</div>", unsafe_allow_html=True)

    with t4:
        st.markdown("<div class='input-card'><h4>💧 Fístula LCR</h4>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1: k, s = st.toggle("Kelly ≥ 2?"), st.toggle("Suprasselar ≥ B?")
        with c2: p, j = st.toggle("Pneumoencéfalo ≥ 3?"), st.number_input("Janela (mm):", 0.0, key="fist_j")
        if st.button("Calcular e Salvar Fístula"):
            res = risco_fistula_lcr_zhang_2025(k, s, p, j)
            st.metric("Risco de Fístula", f"{res:.1f}%")
            salvar_registro(st.session_state.paciente_ativo['nome'], st.session_state.paciente_ativo['mae'], st.session_state.paciente_ativo['prontuario'], "Risco Fístula LCR", res, "risco")
        with st.expander("📚 Referência"): st.markdown("Zhang J, et al. *Front Endocrinol*. 2025. DOI: 10.3389/fendo.2025.1695573")
        st.markdown("</div>", unsafe_allow_html=True)

    with t5:
        st.markdown("<div class='input-card'><h4>🚰 Diabetes Insipidus</h4>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1: d, h, ca = st.checkbox("Diabetes?"), st.checkbox("HAS?"), st.checkbox("Cardiopatia?")
        with c2: co, f, r = st.number_input("Cortisol:", 0.0, key="di_c"), st.toggle("Fístula pós-op?"), st.toggle("Tumor rígido?")
        if st.button("Calcular e Salvar D.I."):
            res = risco_diabetes_insipidus_li_2024(d, h, ca, co, f, r)
            st.metric("Risco D.I.", f"{res:.1f}%")
            salvar_registro(st.session_state.paciente_ativo['nome'], st.session_state.paciente_ativo['mae'], st.session_state.paciente_ativo['prontuario'], "Diabetes Insipidus", res, "risco")
        with st.expander("📚 Referência"): st.markdown("Li XJ, et al. *Heliyon*. 2024. DOI: 10.1016/j.heliyon.2024.e38694")
        st.markdown("</div>", unsafe_allow_html=True)

    with t6:
        st.markdown("<div class='input-card'><h4>🧂 Hiponatremia Tardia</h4>", unsafe_allow_html=True)
        mod = st.radio("Modelo:", ["Sangue", "Imagem/PRL"])
        hp = st.toggle("Hipo D1-D2?")
        if mod == "Sangue":
            mo, pt = st.number_input("Monócitos %:", 0.0, key="h_mo"), st.number_input("PT:", 0.0, key="h_pt")
            if st.button("Calcular Cai"):
                res = risco_pdh_cai_2023(hp, mo, pt)
                st.metric("Risco DPH", f"{res:.1f}%")
                salvar_registro(st.session_state.paciente_ativo['nome'], st.session_state.paciente_ativo['mae'], st.session_state.paciente_ativo['prontuario'], "DPH (Cai)", res, "risco")
        else:
            pr, di = st.number_input("PRL:", 0.0, key="h_pr"), st.number_input("Diafragma (mm):", 0.0, key="h_di")
            if st.button("Calcular Tan"):
                res = risco_pdh_tan_2025(pr, di, hp)
                st.metric("Risco DPH", f"{res:.1f}%")
                salvar_registro(st.session_state.paciente_ativo['nome'], st.session_state.paciente_ativo['mae'], st.session_state.paciente_ativo['prontuario'], "DPH (Tan)", res, "risco")
        st.markdown("</div>", unsafe_allow_html=True)

elif nav == "⚙️ Banco de Dados Geral":
    st.title("⚙️ Banco de Dados Clínico")
    if os.path.exists(ARQUIVO_CSV):
        df = pd.read_csv(ARQUIVO_CSV)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.download_button("📥 Exportar CSV", df.to_csv(index=False).encode('utf-8'), "historico_hugv.csv", "text/csv")
