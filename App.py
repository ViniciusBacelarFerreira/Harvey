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
# FUNÇÕES DE CÁLCULO (BACK-END)
# ==========================================
def risco_pdh_cai_2023(teve_hiponatremia_pod1_2, monocitos_perc, pt_segundos):
    beta_hypo, beta_mono, beta_pt = 0.97, 0.20, 0.58
    beta_0 = -12.50 # PRECISA DE CALIBRAÇÃO
    x_hypo = 1 if teve_hiponatremia_pod1_2 else 0
    logit = beta_0 + (beta_hypo * x_hypo) + (beta_mono * monocitos_perc) + (beta_pt * pt_segundos)
    return (1 / (1 + math.exp(-logit))) * 100

def risco_pdh_tan_2025(prl_pre_op, elevacao_diafragma_mm, teve_hiponatremia_d1_d2):
    beta_prl, beta_elevacao, beta_hipo_precoce = 0.00995, 0.501, 3.486
    beta_0 = -7.50 # PRECISA DE CALIBRAÇÃO
    x_hipo_precoce = 1 if teve_hiponatremia_d1_d2 else 0
    logit = beta_0 + (beta_prl * prl_pre_op) + (beta_elevacao * elevacao_diafragma_mm) + (beta_hipo_precoce * x_hipo_precoce)
    return (1 / (1 + math.exp(-logit))) * 100

def risco_fistula_lcr_zhang_2025(kelly_maior_igual_2, suprasselar_maior_igual_B, pneumoencefalo_maior_igual_3, tamanho_janela_ossea_mm):
    beta_kelly, beta_supra, beta_pneumo, beta_janela = 1.55, 1.77, 2.56, 0.18
    beta_0 = -10.00 # PRECISA DE CALIBRAÇÃO
    x_kelly = 1 if kelly_maior_igual_2 else 0
    x_supra = 1 if suprasselar_maior_igual_B else 0
    x_pneumo = 1 if pneumoencefalo_maior_igual_3 else 0
    logit = beta_0 + (beta_kelly * x_kelly) + (beta_supra * x_supra) + (beta_pneumo * x_pneumo) + (beta_janela * tamanho_janela_ossea_mm)
    return (1 / (1 + math.exp(-logit))) * 100

def risco_diabetes_insipidus_li_2024(tem_diabetes, tem_hipertensao, tem_cardiopatia, cortisol_pre_op, teve_fistula_pos_op, textura_tumor_rigida):
    beta_diabetes, beta_hipertensao, beta_cardiopatia = 0.845, 0.672, 1.039
    beta_cortisol, beta_fistula, beta_textura = 0.001, 1.121, 0.776
    beta_0 = -6.50 # PRECISA DE CALIBRAÇÃO
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
# GESTÃO DE DADOS DO PACIENTE
# ==========================================
def obter_classificacao(probabilidade, tipo="risco"):
    if tipo == "melhora":
        if probabilidade >= 60: return "Alta Chance"
        elif probabilidade >= 30: return "Chance Moderada"
        else: return "Baixa Chance"
    else:
        if probabilidade < 20: return "Baixo Risco"
        elif probabilidade < 50: return "Risco Moderado"
        else: return "Alto Risco"

def salvar_registro(paciente, mae, prontuario, modulo_analise, probabilidade, tipo="risco"):
    classificacao = obter_classificacao(probabilidade, tipo)
    data_hora = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    
    novo_dado = pd.DataFrame([{
        "Data/Hora": data_hora,
        "Prontuário": prontuario,
        "Paciente": paciente,
        "Mãe": mae,
        "Avaliação Clínica": modulo_analise,
        "Resultado (%)": round(probabilidade, 1),
        "Classificação": classificacao,
        "Tipo": tipo
    }])
    
    if os.path.exists(ARQUIVO_CSV):
        df = pd.read_csv(ARQUIVO_CSV)
        df = pd.concat([df, novo_dado], ignore_index=True)
    else:
        df = novo_dado
    df.to_csv(ARQUIVO_CSV, index=False)

# ==========================================
# ESTILOS CSS AVANÇADOS (UI/UX)
# ==========================================
st.markdown("""
<style>
    body { background-color: #f4f7f6; }
    
    .main-title { 
        background: -webkit-linear-gradient(45deg, #0b2e59, #1565c0); 
        -webkit-background-clip: text; 
        -webkit-text-fill-color: transparent; 
        font-weight: 900; 
        font-size: 3.2rem; 
        margin-bottom: 0; 
        text-align: center; 
    }
    .harvey-text {
        font-family: 'Georgia', serif;
        font-style: italic;
        background: -webkit-linear-gradient(45deg, #b8860b, #ffd700);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: normal;
        margin-left: 10px;
    }
    
    .patient-header { background: linear-gradient(135deg, #0b2e59, #1565c0); color: white; padding: 20px 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center;}
    .patient-header h2 { margin: 0; font-size: 2.2rem; color: white; }
    .patient-header p { margin: 5px 0 0 0; font-size: 1.1rem; opacity: 0.9; }
    
    .dashboard-card { background-color: white; border-radius: 12px; padding: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); text-align: center; border-bottom: 5px solid #ddd; height: 100%; transition: transform 0.3s; }
    .dashboard-card:hover { transform: translateY(-5px); }
    .dashboard-card h4 { color: #555; font-size: 1rem; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 15px; }
    .dashboard-card .value { font-size: 2.8rem; font-weight: 800; margin: 10px 0; }
    .dashboard-card .date { font-size: 0.8rem; color: #999; }
    
    .border-green { border-bottom-color: #2e7d32 !important; } .text-green { color: #2e7d32 !important; }
    .border-yellow { border-bottom-color: #f57c00 !important; } .text-yellow { color: #f57c00 !important; }
    .border-red { border-bottom-color: #c62828 !important; } .text-red { color: #c62828 !important; }
    
    .input-card { background-color: #ffffff; padding: 25px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.04); margin-top: 15px; border: 1px solid #e0e0e0; }
    div.stButton > button { width: 100%; border-radius: 8px; background: linear-gradient(135deg, #1565c0, #0b2e59); color: white; font-weight: bold; font-size: 1.1rem; padding: 10px; border: none; transition: 0.2s; }
    div.stButton > button:hover { transform: translateY(-2px); box-shadow: 0 5px 15px rgba(21, 101, 192, 0.4); }
    
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    .stTabs [data-baseweb="tab"] { background-color: #f0f2f6; border-radius: 8px 8px 0 0; padding: 10px 20px; }
    .stTabs [aria-selected="true"] { background-color: #1565c0 !important; color: white !important; font-weight: bold; }
</style>
""", unsafe_allow_html=True)


# ==========================================
# BARRA LATERAL (MENU DE NAVEGAÇÃO)
# ==========================================
def deslogar_paciente():
    st.session_state.paciente_ativo = {"nome": "", "mae": "", "prontuario": ""}

with st.sidebar:
    st.markdown("<div style='text-align: center;'>", unsafe_allow_html=True)
    st.image("https://cdn-icons-png.flaticon.com/512/3022/3022585.png", width=80)
    st.markdown("<h2 style='color: #0b2e59; margin-top: 10px; margin-bottom: 0px;'>NeuroPreditor <span style='font-family: Georgia; font-style: italic; color: #b8860b;'>Harvey</span></h2>", unsafe_allow_html=True)
    st.markdown("<p style='color: #888; font-size: 0.85rem; font-style: italic; margin-top: 0px;'>Made by Vinícius Bacelar Ferreira</p>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("---")
    
    nav_principal = st.radio("Menu Principal:", ["🏠 Área de Trabalho (Prontuários)", "⚙️ Banco de Dados Geral"])
    
    if st.session_state.paciente_ativo['prontuario']:
        st.markdown("---")
        st.info(f"Paciente Ativo:\n**{st.session_state.paciente_ativo['nome']}**")
        st.button("❌ Fechar Prontuário Atual", on_click=deslogar_paciente, type="primary")


# ==========================================
# CABEÇALHO GLOBAL DA APLICAÇÃO
# ==========================================
if not st.session_state.paciente_ativo['prontuario'] and nav_principal == "🏠 Área de Trabalho (Prontuários)":
    st.markdown("<h1 class='main-title'>NeuroPreditor Transesfenoidal <span class='harvey-text'>Harvey</span></h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #888; font-size: 1.1rem; margin-top: -5px; margin-bottom: 25px;'><em>Made by Vinícius Bacelar Ferreira</em></p>", unsafe_allow_html=True)

    st.markdown("""
    <div style='max-width: 900px; margin: 0 auto 35px auto; padding: 20px 30px; background-color: #ffffff; border-left: 6px solid #b8860b; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.06); text-align: center;'>
        <p style='font-size: 1.25rem; color: #333; font-style: italic; margin-bottom: 12px; font-weight: 500; line-height: 1.5;'>
            "O médico deve considerar mais do que um órgão doente, mais até do que o homem inteiro — ele deve ver o homem em seu mundo."
        </p>
        <p style='font-size: 0.95rem; color: #b8860b; font-weight: 800; margin: 0; text-transform: uppercase; letter-spacing: 1.5px;'>— Harvey Cushing</p>
    </div>
    """, unsafe_allow_html=True)

# ==========================================
# ÁREA DE TRABALHO: NENHUM PACIENTE ATIVO
# ==========================================
if nav_principal == "🏠 Área de Trabalho (Prontuários)":
    
    if not st.session_state.paciente_ativo['prontuario']:
        col_busca, col_novo = st.columns([1, 1])
        with col_busca:
            st.markdown("<div class='input-card'>", unsafe_allow_html=True)
            st.subheader("🔍 Buscar Paciente Existente")
            busca_prontuario = st.text_input("Número do Prontuário:")
            if st.button("Acessar Prontuário"):
                if os.path.exists(ARQUIVO_CSV):
                    df = pd.read_csv(ARQUIVO_CSV)
                    paciente_df = df[df['Prontuário'].astype(str) == str(busca_prontuario)]
                    if not paciente_df.empty:
                        st.session_state.paciente_ativo['prontuario'] = busca_prontuario
                        st.session_state.paciente_ativo['nome'] = paciente_df.iloc[0]['Paciente']
                        st.session_state.paciente_ativo['mae'] = paciente_df.iloc[0]['Mãe']
                        st.rerun() 
                    else:
                        st.error("❌ Paciente não encontrado.")
                else:
                    st.error("❌ Banco de dados vazio.")
            st.markdown("</div>", unsafe_allow_html=True)
            
        with col_novo:
            st.markdown("<div class='input-card'>", unsafe_allow_html=True)
            st.subheader("➕ Novo Paciente")
            novo_nome = st.text_input("Nome Completo")
            novo_mae = st.text_input("Nome da Mãe")
            novo_pront = st.text_input("Prontuário")
            if st.button("Criar e Abrir Prontuário"):
                if novo_nome and novo_pront:
                    st.session_state.paciente_ativo['nome'] = novo_nome
                    st.session_state.paciente_ativo['mae'] = novo_mae
                    st.session_state.paciente_ativo['prontuario'] = novo_pront
                    st.rerun() 
                else:
                    st.warning("⚠️ Nome e Prontuário são obrigatórios.")
            st.markdown("</div>", unsafe_allow_html=True)

# ==========================================
# ÁREA DE TRABALHO: PACIENTE ATIVO (O PRONTUÁRIO)
# ==========================================
    if st.session_state.paciente_ativo['prontuario']:
        # Cabeçalho do Prontuário
        st.markdown(f"""
        <div class="patient-header">
            <div>
                <p style="text-transform: uppercase; font-size: 0.9rem; letter-spacing: 1px; margin-bottom: 0px; color: #bbdefb;">Prontuário Eletrônico Aberto</p>
                <h2>👤 {st.session_state.paciente_ativo['nome']}</h2>
            </div>
            <div style="text-align: right;">
                <p><strong>Registro:</strong> {st.session_state.paciente_ativo['prontuario']}</p>
                <p><strong>Mãe:</strong> {st.session_state.paciente_ativo['mae']}</p>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # SISTEMA DE ABAS (TABS) PARA AS AVALIAÇÕES
        tab_hist, tab_vis, tab_cush, tab_fist, tab_di, tab_hipo = st.tabs([
            "📊 Resumo Geral", 
            "👁️ Visão (Pré-op)", 
            "🔄 Cushing (Recorrência)", 
            "💧 Fístula (Bloco)", 
            "🚰 Diabetes Insipidus", 
            "🧂 Hiponatremia (DPH)"
        ])
        
        # --- ABA 1: RESUMO (HISTÓRICO) ---
        with tab_hist:
            st.markdown("### 📊 Painel Consolidado de Riscos Calculados")
            if os.path.exists(ARQUIVO_CSV):
                df = pd.read_csv(ARQUIVO_CSV)
                df_paciente = df[df['Prontuário'].astype(str) == str(st.session_state.paciente_ativo['prontuario'])]
                
                if not df_paciente.empty:
                    df_latest = df_paciente.sort_values('Data/Hora').groupby('Avaliação Clínica').tail(1)
                    cols = st.columns(3)
                    col_idx = 0
                    
                    for _, row in df_latest.iterrows():
                        aval = row['Avaliação Clínica']
                        val = row['Resultado (%)']
                        classif = row['Classificação']
                        data_aval = row['Data/Hora']
                        tipo = row.get('Tipo', 'risco')
                        
                        cor_css = ""
                        if tipo == "melhora":
                            if val >= 60: cor_css = "green"
                            elif val >= 30: cor_css = "yellow"
                            else: cor_css = "red"
                        else:
                            if val < 20: cor_css = "green"
                            elif val < 50: cor_css = "yellow"
                            else: cor_css = "red"
                            
                        with cols[col_idx % 3]:
                            st.markdown(f"""
                            <div class="dashboard-card border-{cor_css}">
                                <h4>{aval}</h4>
                                <div class="value text-{cor_css}">{val}%</div>
                                <div style="font-weight: bold; color: #555;">{classif}</div>
                                <div class="date">Avaliado em: {data_aval}</div>
                            </div>
                            <br>
                            """, unsafe_allow_html=True)
                        col_idx += 1
                else:
                    st.info("Nenhuma avaliação registrada ainda. Navegue pelas abas acima para realizar os cálculos.")
            else:
                 st.info("Nenhuma avaliação registrada ainda. Navegue pelas abas acima para realizar os cálculos.")

        # --- ABA 2: VISÃO ---
        with tab_vis:
            st.markdown("<div class='input-card'>", unsafe_allow_html=True)
            st.markdown("#### 👁️ Previsão de Melhora do Campo Visual")
            col1, col2 = st.columns(2)
            with col1:
                compressao = st.toggle("Compressão do quiasma óptico visível?")
                difuso = st.toggle("Defeito campimétrico difuso?")
            with col2:
                meses = st.number_input("Duração dos sintomas (meses)", min_value=0, value=6)
                md = st.number_input("Mean Defect - MD (dB)", min_value=0.0, value=10.0, step=0.5)
                
            if st.button("🧠 Calcular e Salvar - Visão"):
                resultado = risco_melhora_visual_ji_2023(compressao, difuso, meses, md)
                st.metric("Chance Estimada de Melhora", f"{resultado:.1f}%")
                salvar_registro(st.session_state.paciente_ativo['nome'], st.session_state.paciente_ativo['mae'], st.session_state.paciente_ativo['prontuario'], "Prognóstico Visual", resultado, "melhora")
                st.success("✅ Salvo no prontuário!")
            
            with st.expander("📚 Referência Científica (Algoritmo)"):
                st.markdown("""
                **Referência (Vancouver):**
                Ji X, Zhuang X, Yang S, Zhang K, Li X, Yuan K, et al. Visual field improvement after endoscopic transsphenoidal surgery in patients with pituitary adenoma. *Front Oncol*. 2023;13:1108883.
                
                **DOI:** [10.3389/fonc.2023.1108883](https://doi.org/10.3389/fonc.2023.1108883)
                """)
            st.markdown("</div>", unsafe_allow_html=True)

        # --- ABA 3: CUSHING ---
        with tab_cush:
            st.markdown("<div class='input-card'>", unsafe_allow_html=True)
            st.markdown("#### 🔄 Modelo CuPeR: Risco de Recorrência (Cushing)")
            col1, col2 = st.columns(2)
            with col1:
                meses_cushing = st.number_input("Duração dos sintomas (meses)", min_value=0, value=24)
                cirurgia = st.toggle("Possui cirurgia pituitária prévia?")
            with col2:
                hardy = st.select_slider("Grau de Invasão de Hardy", options=[0, 1, 2, 3, 4], value=2)
                loc = st.selectbox("Localização do Adenoma na RM", ["Bilateral", "Direita", "Esquerda", "Central", "Haste"])
                
            if st.button("🧠 Calcular e Salvar - Cushing"):
                resultado = risco_recorrencia_cushing_cuper_2025(meses_cushing, hardy, loc, cirurgia)
                st.metric("Risco de Recorrência", f"{resultado:.1f}%")
                salvar_registro(st.session_state.paciente_ativo['nome'], st.session_state.paciente_ativo['mae'], st.session_state.paciente_ativo['prontuario'], "Recorrência Cushing (CuPeR)", resultado, "risco")
                st.success("✅ Salvo no prontuário!")
                
            with st.expander("📚 Referência Científica (Algoritmo)"):
                st.markdown("""
                **Referência (Vancouver):**
                Sharifi G, Paraandavaji E, Akbari Dilmaghani N, Emami Meybodi T, Mohammadzadeh I, Sadeghi N, et al. The CuPeR model: A dynamic online tool for predicting Cushing's disease persistence and recurrence after pituitary surgery. *J Clin Transl Endocrinol*. 2025;41:100417.
                
                **DOI:** [10.1016/j.jcte.2025.100417](https://doi.org/10.1016/j.jcte.2025.100417)
                """)
            st.markdown("</div>", unsafe_allow_html=True)

        # --- ABA 4: FÍSTULA ---
        with tab_fist:
            st.markdown("<div class='input-card'>", unsafe_allow_html=True)
            st.markdown("#### 💧 Previsão de Fístula LCR Pós-operatória")
            col1, col2 = st.columns(2)
            with col1:
                kelly = st.toggle("Grau de Kelly Intraop ≥ 2?")
                suprasselar = st.toggle("Extensão Suprasselar ≥ Grau B?")
            with col2:
                pneumo = st.toggle("Pneumoencéfalo Pós-op ≥ Grau 3?")
                janela = st.number_input("Janela óssea do assoalho selar (mm)", min_value=0.0, value=20.0, step=1.0)
                
            if st.button("🧠 Calcular e Salvar - Fístula"):
                resultado = risco_fistula_lcr_zhang_2025(kelly, suprasselar, pneumo, janela)
                st.metric("Risco de Fístula LCR", f"{resultado:.1f}%")
                salvar_registro(st.session_state.paciente_ativo['nome'], st.session_state.paciente_ativo['mae'], st.session_state.paciente_ativo['prontuario'], "Risco Fístula LCR", resultado, "risco")
                st.success("✅ Salvo no prontuário!")
                
            with st.expander("📚 Referência Científica (Algoritmo)"):
                st.markdown("""
                **Referência (Vancouver):**
                Zhang J, He Y, Ning Y, Bai R, Wang H. Risk factors and predictive model for postoperative cerebrospinal fluid leakage following endoscopic endonasal pituitary adenoma surgery: a retrospective study focusing on pneumocephalus and sellar floor bony window. *Front Endocrinol*. 2025;16:1695573.
                
                **DOI:** [10.3389/fendo.2025.1695573](https://doi.org/10.3389/fendo.2025.1695573)
                """)
            st.markdown("</div>", unsafe_allow_html=True)

        # --- ABA 5: DIABETES INSIPIDUS ---
        with tab_di:
            st.markdown("<div class='input-card'>", unsafe_allow_html=True)
            st.markdown("#### 🚰 Risco de Diabetes Insipidus Pós-operatório")
            col1, col2, col3 = st.columns(3)
            with col1: dm = st.toggle("Diabetes Mellitus")
            with col2: has = st.toggle("Hipertensão")
            with col3: cardio = st.toggle("Cardiopatia")
            st.markdown("---")
            col4, col5 = st.columns(2)
            with col4: cortisol = st.number_input("Cortisol Pré-op (mmol/L)", min_value=0.0, value=300.0, step=10.0)
            with col5:
                fistula_previa = st.toggle("Houve Fístula LCR Pós-op?")
                rigido = st.toggle("Textura tumoral maciça/rígida?")
                
            if st.button("🧠 Calcular e Salvar - D.I."):
                resultado = risco_diabetes_insipidus_li_2024(dm, has, cardio, cortisol, fistula_previa, rigido)
                st.metric("Risco de Diabetes Insipidus", f"{resultado:.1f}%")
                salvar_registro(st.session_state.paciente_ativo['nome'], st.session_state.paciente_ativo['mae'], st.session_state.paciente_ativo['prontuario'], "Diabetes Insipidus", resultado, "risco")
                st.success("✅ Salvo no prontuário!")
                
            with st.expander("📚 Referência Científica (Algoritmo)"):
                st.markdown("""
                **Referência (Vancouver):**
                Li XJ, Peng Z, Wang YF, Wang J, Yan HY, Jin W, et al. Analysis of factors influencing the occurrence of diabetes insipidus following neuroendoscopic transsphenoidal resection of pituitary adenomas and risk assessment. *Heliyon*. 2024;10(1):e38694.
                
                **DOI:** [10.1016/j.heliyon.2024.e38694](https://doi.org/10.1016/j.heliyon.2024.e38694)
                """)
            st.markdown("</div>", unsafe_allow_html=True)

        # --- ABA 6: HIPONATREMIA TARDIA ---
        with tab_hipo:
            st.markdown("<div class='input-card'>", unsafe_allow_html=True)
            st.markdown("#### 🧂 Risco de Hiponatremia Tardia (DPH)")
            modelo_escolhido = st.radio("Selecione o modelo baseado nos exames:", ["Sangue (Monócitos + PT)", "Hormonal/Imagem (Prolactina + RM)"])
            
            col1, col2 = st.columns(2)
            if "Sangue" in modelo_escolhido:
                with col1:
                    hipo_1_2 = st.toggle("Queda de Sódio no D1-D2?", key="h1")
                    mono = st.number_input("Monócitos (%)", min_value=0.0, value=7.0, step=0.1)
                with col2:
                    pt = st.number_input("PT (segundos)", min_value=0.0, value=11.5, step=0.1)
                if st.button("🧠 Calcular e Salvar (Modelo Cai)"):
                    resultado = risco_pdh_cai_2023(hipo_1_2, mono, pt)
                    st.metric("Risco de DPH (Mod. Cai)", f"{resultado:.1f}%")
                    salvar_registro(st.session_state.paciente_ativo['nome'], st.session_state.paciente_ativo['mae'], st.session_state.paciente_ativo['prontuario'], "Hiponatremia DPH (Cai)", resultado, "risco")
                    st.success("✅ Salvo no prontuário!")
                    
                with st.expander("📚 Referência Científica (Algoritmo)"):
                    st.markdown("""
                    **Referência (Vancouver):**
                    Cai X, Zhang A, Zhao P, Liu Z, Aili Y, Zeng X, et al. Predictors and dynamic online nomogram for postoperative delayed hyponatremia after endoscopic transsphenoidal surgery for pituitary adenomas: a single-center, retrospective, observational cohort study with external validation. *Chin Neurosurg J*. 2023;9(1):19.
                    
                    **DOI:** [10.1186/s41016-023-00334-3](https://doi.org/10.1186/s41016-023-00334-3)
                    """)
            else:
                with col1:
                    hipo_1_2_tan = st.toggle("Queda de Sódio no D1-D2?", key="h2")
                    prl = st.number_input("Prolactina Pré-op (ng/mL)", min_value=0.0, value=25.0)
                with col2:
                    diafragma = st.number_input("Elevação pré-op do diafragma (mm)", min_value=0.0, value=10.0, step=0.5)
                if st.button("🧠 Calcular e Salvar (Modelo Tan)"):
                    resultado = risco_pdh_tan_2025(prl, diafragma, hipo_1_2_tan)
                    st.metric("Risco de DPH (Mod. Tan)", f"{resultado:.1f}%")
                    salvar_registro(st.session_state.paciente_ativo['nome'], st.session_state.paciente_ativo['mae'], st.session_state.paciente_ativo['prontuario'], "Hiponatremia DPH (Tan)", resultado, "risco")
                    st.success("✅ Salvo no prontuário!")
                    
                with st.expander("📚 Referência Científica (Algoritmo)"):
                    st.markdown("""
                    **Referência (Vancouver):**
                    Tan H, Miao X, Pei Y, Miao F. Predictive model of delayed hyponatremia after endoscopic endonasal transsphenoidal resection of pituitary adenoma. *Front Hum Neurosci*. 2025;19:1674519.
                    
                    **DOI:** [10.3389/fnhum.2025.1674519](https://doi.org/10.3389/fnhum.2025.1674519)
                    """)
            st.markdown("</div>", unsafe_allow_html=True)

# ==========================================
# MÓDULO: BANCO DE DADOS GERAL
# ==========================================
elif nav_principal == "⚙️ Banco de Dados Geral":
    st.markdown("<h2 style='color: #0b2e59; text-align: center;'>⚙️ Banco de Dados Clínico Completo</h2>", unsafe_allow_html=True)
    st.write("<p style='text-align: center;'>Visão geral e extração de todos os dados salvos no sistema.</p>", unsafe_allow_html=True)
    st.markdown("---")
    
    if os.path.exists(ARQUIVO_CSV):
        df = pd.read_csv(ARQUIVO_CSV)
        st.dataframe(df, use_container_width=True, hide_index=True)
        
        csv_download = df.to_csv(index=False).encode('utf-8')
        st.write("")
        col_espaco, col_botao, col_espaco2 = st.columns([1, 2, 1])
        with col_botao:
            st.download_button(
                label="📥 Exportar Tabela Completa para Excel (CSV)",
                data=csv_download,
                file_name="banco_dados_transesfenoidal.csv",
                mime="text/csv",
                use_container_width=True
            )
    else:
        st.info("📭 Nenhum dado registrado no sistema ainda.")
