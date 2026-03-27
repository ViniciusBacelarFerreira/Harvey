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
if 'ultimo_resultado' not in st.session_state:
    st.session_state.ultimo_resultado = None

ARQUIVO_CSV = "registro_pacientes.csv"

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
    return min(95.0, max(5.0, probabilidade))

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
# GESTÃO DE DADOS (SALVAMENTO)
# ==========================================
def obter_classificacao(probabilidade, tipo="risco"):
    if tipo == "melhora":
        if probabilidade >= 60: return "Alta Chance", "green"
        elif probabilidade >= 30: return "Chance Moderada", "orange"
        else: return "Baixa Chance", "red"
    else:
        if probabilidade < 20: return "Baixo Risco", "green"
        elif probabilidade < 45: return "Risco Moderado", "orange"
        else: return "Alto Risco", "red"

def salvar_registro(modulo_analise, probabilidade, tipo="risco"):
    paciente = st.session_state.paciente_ativo['nome']
    mae = st.session_state.paciente_ativo['mae']
    prontuario = str(st.session_state.paciente_ativo['prontuario'])
    classificacao, _ = obter_classificacao(probabilidade, tipo)
    data_hora = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    
    novo_dado = pd.DataFrame([{
        "Data/Hora": data_hora, "Prontuário": prontuario, "Paciente": paciente,
        "Mãe": mae, "Avaliação Clínica": modulo_analise, "Resultado (%)": round(probabilidade, 1),
        "Classificação": classificacao, "Tipo": tipo
    }])
    
    try:
        if os.path.exists(ARQUIVO_CSV):
            df_existente = pd.read_csv(ARQUIVO_CSV, dtype={'Prontuário': str})
            df_final = pd.concat([df_existente, novo_dado], ignore_index=True)
        else: df_final = novo_dado
        df_final.to_csv(ARQUIVO_CSV, index=False, encoding='utf-8')
        return True
    except Exception as e:
        st.error(f"Erro ao salvar: {e}")
        return False

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
    .calc-info { background-color: #e3f2fd; padding: 12px; border-radius: 8px; border-left: 5px solid #1565c0; margin-bottom: 20px; font-size: 0.95rem; color: #0d47a1; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# BARRA LATERAL
# ==========================================
def deslogar():
    st.session_state.paciente_ativo = {"nome": "", "mae": "", "prontuario": ""}
    st.session_state.ultimo_resultado = None

with st.sidebar:
    st.markdown("<div style='text-align: center;'>", unsafe_allow_html=True)
    st.markdown("<h4 style='color: #0b2e59; margin-top: 5px;'>HUGV - UFAM</h4>", unsafe_allow_html=True)
    st.markdown("<h2 style='color: #0b2e59; margin-top: 15px;'>NeuroPreditor <span class='harvey-text'>Harvey</span></h2>", unsafe_allow_html=True)
    st.markdown("<p style='color: #888; font-size: 0.8rem;'>Made by Vinícius Bacelar Ferreira</p></div>", unsafe_allow_html=True)
    st.markdown("---")
    nav = st.radio("Menu:", ["🏠 Área de Trabalho", "⚙️ Histórico Geral"])
    if st.session_state.paciente_ativo['prontuario']:
        st.button("❌ Sair do Prontuário", on_click=deslogar, type="primary")

# ==========================================
# HOME PAGE
# ==========================================
if not st.session_state.paciente_ativo['prontuario'] and nav == "🏠 Área de Trabalho":
    st.markdown("<h1 class='main-title'>NeuroPreditor Transesfenoidal <span class='harvey-text'>Harvey</span></h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #888;'><em>Made by Vinícius Bacelar Ferreira</em></p>", unsafe_allow_html=True)
    st.markdown("<div style='max-width: 900px; margin: 0 auto 35px auto; padding: 25px; background:#fff; border-left:6px solid #b8860b; border-radius:12px; box-shadow:0 4px 15px rgba(0,0,0,0.06); text-align: center;'><p style='font-size:1.35rem; font-style:italic;'>\"Gostaria de ver o dia em que alguém fosse nomeado cirurgião sem ter mãos, pois a parte operatória é a menor parte do trabalho.\"</p><p style='color:#b8860b; font-weight:800;'>— HARVEY WILLIAMS CUSHING</p></div>", unsafe_allow_html=True)
    
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("<div class='input-card'><h3>🔍 Aceder a Prontuário</h3>", unsafe_allow_html=True)
        bp = st.text_input("Número do Prontuário:")
        if st.button("Abrir"):
            if os.path.exists(ARQUIVO_CSV):
                df = pd.read_csv(ARQUIVO_CSV, dtype={'Prontuário': str})
                pdf = df[df['Prontuário'] == str(bp)]
                if not pdf.empty:
                    st.session_state.paciente_ativo = {"prontuario": str(bp), "nome": pdf.iloc[0]['Paciente'], "mae": pdf.iloc[0]['Mãe']}
                    st.rerun()
            st.error("Paciente não encontrado.")
    with c2:
        st.markdown("<div class='input-card'><h3>➕ Novo Registro</h3>", unsafe_allow_html=True)
        nn, nm, np = st.text_input("Nome:"), st.text_input("Mãe:"), st.text_input("Prontuário:")
        if st.button("Iniciar Atendimento"):
            if nn and np:
                st.session_state.paciente_ativo = {"nome": nn, "mae": nm, "prontuario": str(np)}
                st.rerun()

# ==========================================
# INTERFACE DO PRONTUÁRIO ATIVO
# ==========================================
if nav == "🏠 Área de Trabalho" and st.session_state.paciente_ativo['prontuario']:
    st.markdown(f'<div class="patient-header"><div><p style="font-size:0.8rem;opacity:0.8;">PRONTUÁRIO ATIVO</p><h2>👤 {st.session_state.paciente_ativo["nome"]}</h2></div><div><p>Registro: {st.session_state.paciente_ativo["prontuario"]}</p></div></div>', unsafe_allow_html=True)
    tabs = st.tabs(["📊 Painel", "👁️ Visão", "🔄 Cushing", "💧 Fístula", "🚰 D.I.", "🧂 Hiponatremia"])

    # --- ABA PAINEL (RESUMO VISUAL) ---
    with tabs[0]:
        st.subheader("📊 Últimos Resultados Arquivados")
        if os.path.exists(ARQUIVO_CSV):
            df_hist = pd.read_csv(ARQUIVO_CSV, dtype={'Prontuário': str})
            df_pac = df_hist[df_hist['Prontuário'] == str(st.session_state.paciente_ativo['prontuario'])]
            if not df_pac.empty:
                df_latest = df_pac.sort_values(by="Data/Hora").groupby("Avaliação Clínica").last().reset_index()
                cols = st.columns(3)
                for index, row in df_latest.iterrows():
                    val = float(row['Resultado (%)'])
                    label, cor = obter_classificacao(val, row['Tipo'])
                    with cols[index % 3]:
                        st.markdown(f'<div class="dashboard-card b-{cor}"><div style="font-weight:bold;color:#555;">{row["Avaliação Clínica"]}</div><div class="card-value t-{cor}">{val}%</div><div style="font-weight:bold;" class="t-{cor}">{label}</div><div style="font-size:0.7rem;color:#aaa;">{row["Data/Hora"]}</div></div><br>', unsafe_allow_html=True)
            else: st.info("Sem cálculos arquivados.")

    # --- ABA VISÃO ---
    with tabs[1]:
        st.markdown("<div class='calc-info'><strong>O que calcula:</strong> Probabilidade de melhora campimétrica pós-op.</div>", unsafe_allow_html=True)
        st.markdown("<div class='input-card'>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1: 
            v_q = st.toggle("Compressão do quiasma?", help="Distorção visível na RM coronal.")
            v_d = st.toggle("Defeito difuso?", help="Queda generalizada na campimetria.")
        with c2: 
            v_m = st.number_input("Duração sintomas (meses):", 0)
            v_md = st.number_input("MD (dB) pré-op:", 0.0)
        if st.button("Calcular Visão"):
            res = risco_melhora_visual_ji_2023(v_q, v_d, v_m, v_md)
            st.session_state.ultimo_resultado = {"modulo": "Prognóstico Visual", "valor": res, "tipo": "melhora"}
            salvar_registro("Prognóstico Visual", res, "melhora"); st.rerun()
        if st.session_state.ultimo_resultado and st.session_state.ultimo_resultado['modulo'] == "Prognóstico Visual":
            st.metric("Probabilidade", f"{st.session_state.ultimo_resultado['valor']:.1f}%")
        with st.expander("📚 Referência Científica"):
            st.markdown("""
            **Referência (Vancouver):** Ji X, Zhuang X, Yang S, Zhang K, Li X, Yuan K, et al. Visual field improvement after endoscopic transsphenoidal surgery in patients with pituitary adenoma. *Front Oncol*. 2023;13:1108883.  
            **DOI:** [10.3389/fonc.2023.1108883](https://doi.org/10.3389/fonc.2023.1108883)
            """)
        st.markdown("</div>", unsafe_allow_html=True)

    # --- ABA CUSHING ---
    with tabs[2]:
        st.markdown("<div class='calc-info'><strong>O que calcula:</strong> Risco de recorrência/persistência (Modelo CuPeR).</div>", unsafe_allow_html=True)
        st.markdown("<div class='input-card'>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1: 
            c_dur = st.number_input("Meses sintomas (Cushing):", 0)
            c_cp = st.toggle("Cirurgia prévia?")
        with c2: 
            c_h = st.select_slider("Grau de Hardy:", [0,1,2,3,4], value=2)
            c_l = st.selectbox("Localização:", ["Bilateral","Direita","Esquerda","Central","Haste"])
        if st.button("Calcular Cushing"):
            res = risco_recorrencia_cushing_cuper_2025(c_dur, c_h, c_l, c_cp)
            st.session_state.ultimo_resultado = {"modulo": "Recorrência Cushing", "valor": res, "tipo": "risco"}
            salvar_registro("Recorrência Cushing", res, "risco"); st.rerun()
        if st.session_state.ultimo_resultado and st.session_state.ultimo_resultado['modulo'] == "Recorrência Cushing":
            st.metric("Risco", f"{st.session_state.ultimo_resultado['valor']:.1f}%")
        with st.expander("📚 Referência Científica"):
            st.markdown("""
            **Referência (Vancouver):** Sharifi G, Paraandavaji E, Akbari Dilmaghani N, Emami Meybodi T, Mohammadzadeh I, Sadeghi N, et al. The CuPeR model: A dynamic online tool for predicting Cushing's disease persistence and recurrence after pituitary surgery. *J Clin Transl Endocrinol*. 2025;41:100417.  
            **DOI:** [10.1016/j.jcte.2025.100417](https://doi.org/10.1016/j.jcte.2025.100417)
            """)
        st.markdown("</div>", unsafe_allow_html=True)

    # --- ABA FÍSTULA ---
    with tabs[3]:
        st.markdown("<div class='calc-info'><strong>O que calcula:</strong> Risco imediato de fístula de LCR pós-op.</div>", unsafe_allow_html=True)
        st.markdown("<div class='input-card'>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1: 
            f_k = st.toggle("Grau Kelly ≥ 2?", help="Fístula intra-op moderada/alta.")
            f_s = st.toggle("Extensão suprasselar ≥ Grau B?")
        with c2: 
            f_p = st.toggle("Pneumoencéfalo ≥ Grau 3?", help="Acentuado na TC de 24h.")
            f_j = st.number_input("Janela óssea (mm):", 0.0)
        if st.button("Calcular Fístula"):
            res = risco_fistula_lcr_zhang_2025(f_k, f_s, f_p, f_j)
            st.session_state.ultimo_resultado = {"modulo": "Risco Fístula LCR", "valor": res, "tipo": "risco"}
            salvar_registro("Risco Fístula LCR", res, "risco"); st.rerun()
        if st.session_state.ultimo_resultado and st.session_state.ultimo_resultado['modulo'] == "Risco Fístula LCR":
            st.metric("Risco", f"{st.session_state.ultimo_resultado['valor']:.1f}%")
        with st.expander("📚 Referência Científica"):
            st.markdown("""
            **Referência (Vancouver):** Zhang J, He Y, Ning Y, Bai R, Wang H. Risk factors and predictive model for postoperative cerebrospinal fluid leakage... *Front Endocrinol*. 2025;16:1695573.  
            **DOI:** [10.3389/fendo.2025.1695573](https://doi.org/10.3389/fendo.2025.1695573)
            """)
        st.markdown("</div>", unsafe_allow_html=True)

    # --- ABA D.I. ---
    with tabs[4]:
        st.markdown("<div class='calc-info'><strong>O que calcula:</strong> Risco de Diabetes Insipidus central pós-op.</div>", unsafe_allow_html=True)
        st.markdown("<div class='input-card'>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1: 
            di_d = st.checkbox("Diabetes Mellitus?"); di_h = st.checkbox("Hipertensão?"); di_ca = st.checkbox("Cardiopatia?")
        with c2: 
            di_co = st.number_input("Cortisol pré-op:", 0.0)
            di_f = st.toggle("Fístula pós-op?"); di_r = st.toggle("Tumor rígido?")
        if st.button("Calcular D.I."):
            res = risco_diabetes_insipidus_li_2024(di_d, di_h, di_ca, di_co, di_f, di_r)
            st.session_state.ultimo_resultado = {"modulo": "Diabetes Insipidus", "valor": res, "tipo": "risco"}
            salvar_registro("Diabetes Insipidus", res, "risco"); st.rerun()
        if st.session_state.ultimo_resultado and st.session_state.ultimo_resultado['modulo'] == "Diabetes Insipidus":
            st.metric("Risco", f"{st.session_state.ultimo_resultado['valor']:.1f}%")
        with st.expander("📚 Referência Científica"):
            st.markdown("""
            **Referência (Vancouver):** Li XJ, Peng Z, Wang YF, Wang J, Yan HY, Jin W, et al. Analysis of factors influencing the occurrence of diabetes insipidus... *Heliyon*. 2024;10(1):e38694.  
            **DOI:** [10.1016/j.heliyon.2024.e38694](https://doi.org/10.1016/j.heliyon.2024.e38694)
            """)
        st.markdown("</div>", unsafe_allow_html=True)

    # --- ABA HIPONATREMIA ---
    with tabs[5]:
        st.markdown("<div class='calc-info'><strong>O que calcula:</strong> Risco de Hiponatremia Tardia (DPH) após a alta.</div>", unsafe_allow_html=True)
        st.markdown("<div class='input-card'>", unsafe_allow_html=True)
        mod_h = st.radio("Modelo:", ["Cai et al. (Sangue)", "Tan et al. (Imagem)"])
        hp_12 = st.toggle("Hipo nos dias 1-2?")
        if mod_h == "Cai et al. (Sangue)":
            h_mo = st.number_input("Monócitos %:", 0.0); h_pt = st.number_input("PT (seg):", 0.0)
            if st.button("Calcular DPH"):
                res = risco_pdh_cai_2023(hp_12, h_mo, h_pt)
                st.session_state.ultimo_resultado = {"modulo": "DPH (Cai)", "valor": res, "tipo": "risco"}
                salvar_registro("DPH (Cai)", res, "risco"); st.rerun()
            with st.expander("📚 Referência"):
                st.markdown("Cai X, et al. *Chin Neurosurg J*. 2023. DOI: 10.1186/s41016-023-00334-3")
        else:
            h_pr = st.number_input("PRL pré-op:", 0.0); h_di = st.number_input("Diafragma (mm):", 0.0)
            if st.button("Calcular DPH"):
                res = risco_pdh_tan_2025(h_pr, h_di, hp_12)
                st.session_state.ultimo_resultado = {"modulo": "DPH (Tan)", "valor": res, "tipo": "risco"}
                salvar_registro("DPH (Tan)", res, "risco"); st.rerun()
            with st.expander("📚 Referência"):
                st.markdown("Tan H, et al. *Front Hum Neurosci*. 2025. DOI: 10.3389/fnhum.2025.1674519")
        if st.session_state.ultimo_resultado and "DPH" in st.session_state.ultimo_resultado['modulo']:
            st.metric("Risco", f"{st.session_state.ultimo_resultado['valor']:.1f}%")
        st.markdown("</div>", unsafe_allow_html=True)

# ==========================================
# HISTÓRICO GERAL
# ==========================================
elif nav == "⚙️ Histórico Geral":
    st.title("⚙️ Banco de Dados Clínico")
    if os.path.exists(ARQUIVO_CSV):
        df_geral = pd.read_csv(ARQUIVO_CSV, dtype={'Prontuário': str})
        st.dataframe(df_geral.sort_values(by="Data/Hora", ascending=False), use_container_width=True, hide_index=True)
        st.download_button("📥 Exportar CSV", df_geral.to_csv(index=False).encode('utf-8'), "historico_hugv.csv", "text/csv")
    else: st.info("Sem dados.")
        
