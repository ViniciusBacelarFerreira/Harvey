import streamlit as st
import streamlit.components.v1 as components
import math
import pandas as pd
import datetime
import os
import sqlite3
import plotly.graph_objects as go
import re

# ==========================================
# CONFIGURAÇÃO INICIAL E ESTADO DA SESSÃO
# ==========================================
st.set_page_config(page_title="NeuroPreditor Harvey", layout="wide", page_icon="🧠")

if 'autenticado' not in st.session_state:
    st.session_state.autenticado = False
if 'paciente_ativo' not in st.session_state:
    st.session_state.paciente_ativo = {"nome": "", "mae": "", "prontuario": ""}

# Variáveis para armazenar o resultado (Probabilidade, Contribuições) na tela sem recarregar
lista_modulos = ['visao_res', 'cushing_res', 'fistula_intra_res', 'fistula_res', 'di_res', 'hipo_res', 'meningite_res', 'chen_res', 'acro_res', 'nfpa_res']
for mod in lista_modulos:
    if mod not in st.session_state:
        st.session_state[mod] = None

DB_NAME = "harvey_database.db"
SENHA_CORRETA = "hugv1869"

# ==========================================
# INICIALIZAÇÃO DA BASE DE DADOS (SQLITE)
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS avaliacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_hora TEXT,
            prontuario TEXT,
            paciente TEXT,
            mae TEXT,
            avaliacao_clinica TEXT,
            parametros TEXT,
            resultado REAL,
            classificacao TEXT,
            tipo TEXT
        )
    ''')
    
    # Migração automática do arquivo CSV antigo para SQLite (se existir)
    c.execute("SELECT COUNT(*) FROM avaliacoes")
    if c.fetchone()[0] == 0 and os.path.exists("registro_pacientes.csv"):
        try:
            df_migracao = pd.read_csv("registro_pacientes.csv", dtype={'Prontuário': str})
            for _, row in df_migracao.iterrows():
                param_inseridos = row.get('Parâmetros Inseridos', 'Dados antigos não registrados')
                if pd.isna(param_inseridos): param_inseridos = 'Dados antigos não registrados'
                
                c.execute('''
                    INSERT INTO avaliacoes (data_hora, prontuario, paciente, mae, avaliacao_clinica, parametros, resultado, classificacao, tipo)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (str(row['Data/Hora']), str(row['Prontuário']), str(row['Paciente']), str(row['Mãe']), 
                      str(row['Avaliação Clínica']), str(param_inseridos), float(row['Resultado (%)']), 
                      str(row['Classificação']), str(row['Tipo'])))
            print("Migração do CSV para SQLite concluída com sucesso.")
        except Exception as e:
            print(f"Erro na migração do CSV: {e}")
            
    conn.commit()
    conn.close()

init_db()

# ==========================================
# FUNÇÕES DE XAI E GRÁFICOS
# ==========================================
def gerar_grafico_waterfall(contribuicoes, titulo="Impacto das Variáveis (Modelo Matemático)"):
    labels = list(contribuicoes.keys())
    values = list(contribuicoes.values())
    
    measures = ["relative"] * len(labels)
    labels.append("Resultado Final (Logit)")
    values.append(sum(values))
    measures.append("total")
    
    fig = go.Figure(go.Waterfall(
        orientation="v", measure=measures, x=labels, textposition="outside",
        text=[f"{v:+.2f}" if m == "relative" else f"{v:.2f}" for m, v in zip(measures, values)],
        y=values, connector={"line":{"color":"rgba(128,128,128,0.5)"}},
        decreasing={"marker":{"color":"#1565c0"}}, increasing={"marker":{"color":"#ef6c00"}}, totals={"marker":{"color":"#333333"}}      
    ))
    fig.update_layout(title={"text": titulo, "font": {"size": 14}}, showlegend=False, height=320, margin=dict(l=20, r=20, t=40, b=20), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    return fig

def gerar_grafico_velocimetro(prob, tipo="risco"):
    if tipo == "melhora":
        steps = [{'range': [0, 30], 'color': "rgba(198, 40, 40, 0.8)"}, {'range': [30, 60], 'color': "rgba(239, 108, 0, 0.8)"}, {'range': [60, 100], 'color': "rgba(46, 125, 50, 0.8)"}]
        title = "Probabilidade"
    else:
        steps = [{'range': [0, 15], 'color': "rgba(46, 125, 50, 0.8)"}, {'range': [15, 30], 'color': "rgba(239, 108, 0, 0.8)"}, {'range': [30, 100], 'color': "rgba(198, 40, 40, 0.8)"}]
        title = "Nível de Risco"

    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=prob, number={'suffix': "%", 'font': {'size': 40, 'color': '#333'}},
        domain={'x': [0, 1], 'y': [0, 1]}, title={'text': title, 'font': {'size': 18, 'color': '#555'}},
        gauge={'axis': {'range': [None, 100], 'tickwidth': 1, 'tickcolor': "darkblue"}, 'bar': {'color': "rgba(0, 0, 0, 0.8)", 'thickness': 0.15}, 'bgcolor': "white", 'borderwidth': 2, 'bordercolor': "gray", 'steps': steps}
    ))
    fig.update_layout(height=320, margin=dict(l=20, r=20, t=50, b=20), paper_bgcolor='rgba(0,0,0,0)')
    return fig

def obter_texto_explicativo(contribuicoes):
    contribs_clinicas = {k: v for k, v in contribuicoes.items() if "Base" not in k}
    if not contribs_clinicas: return ""
    max_var = max(contribs_clinicas, key=lambda k: abs(contribs_clinicas[k]))
    max_val = contribs_clinicas[max_var]
    if max_val == 0: return "Nenhum fator de risco adicional pontuou neste paciente."
    acao = "aumentou" if max_val > 0 else "reduziu"
    return f"A variável clínica que mais **{acao}** a probabilidade neste paciente foi: **{max_var}** (Impacto no Logit: {max_val:+.2f})."

def extrair_metricas_parametros(df):
    idades, diametros = [], []
    for p in df['Parâmetros Inseridos'].dropna():
        m_idade = re.search(r'Idade:\s*(\d+)', p)
        if m_idade: idades.append(int(m_idade.group(1)))
        
        m_diam = re.search(r'(?:Diâmetro(?: do Tumor)?|Altura do Tumor):\s*([\d\.]+)', p)
        if m_diam: diametros.append(float(m_diam.group(1)))
        
    med_idade = sum(idades)/len(idades) if idades else 0
    med_diam = sum(diametros)/len(diametros) if diametros else 0
    return med_idade, med_diam

# ==========================================
# FUNÇÕES DE CÁLCULO (BACK-END COM XAI)
# ==========================================
def risco_progressao_nfpa_zhong_2024(ki67_high, knosp_high, resseccao_subtotal):
    beta_0 = -4.0 
    c_ki67 = 1.671 * (1 if ki67_high else 0)
    c_knosp = 2.296 * (1 if knosp_high else 0)
    c_res = 1.771 * (1 if resseccao_subtotal else 0)
    logit = beta_0 + c_ki67 + c_knosp + c_res
    prob = (1 / (1 + math.exp(-logit))) * 100
    return prob, {"Risco Base": beta_0, "Ki-67 ≥3%": c_ki67, "Knosp 3B-4": c_knosp, "Ressecção Incompleta": c_res}

def risco_fistula_intraop_cai_2021(altura_tumor_mm, albumina_gl):
    beta_0 = 3.10
    c_altura = 0.1081 * altura_tumor_mm
    c_albumina = -0.1395 * albumina_gl
    logit = beta_0 + c_altura + c_albumina
    prob = (1 / (1 + math.exp(-logit))) * 100
    return prob, {"Risco Base": beta_0, "Altura Tumor": c_altura, "Albumina Sérica": c_albumina}

def remissao_acromegalia_cohen_2024(idade, diametro, knosp, igf1, gh):
    c_idade = 1 if idade <= 50 else 0
    c_diam = 1 if diametro >= 1.5 else 0
    c_knosp = 3 if knosp in ["Grau 3A", "Grau 3B", "Grau 4"] else 0
    c_igf1 = 2 if igf1 >= 3.0 else 0
    c_gh = 1 if gh >= 8.0 else 0
    pontos = c_idade + c_diam + c_knosp + c_igf1 + c_gh
    prob = {0: 100.0, 1: 90.0, 2: 65.0, 3: 35.0, 4: 15.0, 5: 15.0}.get(pontos, 0.0)
    return prob, {"Base (0 Pontos)": 0, "Idade ≤50": c_idade, "Diâmetro ≥1.5": c_diam, "Knosp ≥3A": c_knosp, "IGF-1 ≥3.0": c_igf1, "GH ≥8.0": c_gh}

def risco_progressao_chen_2021(resection, knosp, ki67, bmi, tabagismo):
    c_res = 10.0 if resection == "Ressecção Parcial (PR < 70%)" else (5.5 if resection == "Ressecção Subtotal (STR 70-90%)" else (3.5 if resection == "Ressecção Quase Total (NTR 90-95%)" else 0))
    c_knosp = 7.5 if knosp == "Grau 4" else (3.8 if knosp == "Graus 2 - 3" else 0)
    c_ki67 = 8.0 if ki67 else 0
    c_bmi = 4.0 if bmi else 0
    c_tab = 6.2 if tabagismo else 0
    logit = -4.0 + (0.2 * (c_res + c_knosp + c_ki67 + c_bmi + c_tab))
    prob = (1 / (1 + math.exp(-logit))) * 100
    return prob, {"Risco Base": -4.0, "Ressecção": c_res*0.2, "Knosp": c_knosp*0.2, "Ki-67": c_ki67*0.2, "IMC": c_bmi*0.2, "Tabagismo": c_tab*0.2}

def risco_meningite_zhou_2025(duracao_h, diametro_cm, fistula_intra):
    c_dur = 0.98 * duracao_h
    c_diam = 0.99 * diametro_cm
    c_fist = 2.22 * (1 if fistula_intra else 0)
    logit = -7.50 + c_dur + c_diam + c_fist
    prob = (1 / (1 + math.exp(-logit))) * 100
    return prob, {"Risco Base": -7.50, "Duração Cirurgia": c_dur, "Diâmetro Tumor": c_diam, "Fístula LCR": c_fist}

def risco_pdh_cai_2023(hipo_precoce, monocitos, pt):
    c_hipo = 0.97 * (1 if hipo_precoce else 0)
    c_mon = 0.20 * monocitos
    c_pt = 0.58 * pt
    logit = -12.50 + c_hipo + c_mon + c_pt
    prob = (1 / (1 + math.exp(-logit))) * 100
    return prob, {"Risco Base": -12.50, "Hipo Precoce": c_hipo, "Monócitos": c_mon, "Protrombina": c_pt}

def risco_pdh_tan_2025(pr, dia, hp12):
    beta_0 = -7.50
    c_pr = 0.00995 * pr
    c_dia = 0.501 * dia
    c_hp = 3.486 * (1 if hp12 else 0)
    logit = beta_0 + c_pr + c_dia + c_hp
    prob = (1 / (1 + math.exp(-logit))) * 100
    return prob, {"Risco Base": beta_0, "Prolactina": c_pr, "Diafragma": c_dia, "Hipo Precoce": c_hp}

def risco_fistula_lcr_zhang_2025(kelly, supra, pneumo, janela):
    c_k = 1.55 * (1 if kelly else 0)
    c_s = 1.77 * (1 if supra else 0)
    c_p = 2.56 * (1 if pneumo else 0)
    c_j = 0.18 * janela
    logit = -10.00 + c_k + c_s + c_p + c_j
    prob = (1 / (1 + math.exp(-logit))) * 100
    return prob, {"Risco Base": -10.00, "Kelly": c_k, "Suprasselar": c_s, "Pneumoencéfalo": c_p, "Janela óssea": c_j}

def risco_diabetes_insipidus_li_2024(dm, has, cardio, cortisol, fistula, rigido):
    c_dm = 0.845 * (1 if dm else 0)
    c_has = 0.672 * (1 if has else 0)
    c_car = 1.039 * (1 if cardio else 0)
    c_cor = 0.001 * cortisol
    c_fist = 1.121 * (1 if fistula else 0)
    c_rig = 0.776 * (1 if rigido else 0)
    logit = -6.50 + c_dm + c_has + c_car + c_cor + c_fist + c_rig
    prob = (1 / (1 + math.exp(-logit))) * 100
    return prob, {"Risco Base": -6.50, "DM": c_dm, "HAS": c_has, "Cardiopatia": c_car, "Cortisol": c_cor, "Fístula LCR": c_fist, "Tumor Rígido": c_rig}

def risco_melhora_visual_ji_2023(comp, dif, meses, md):
    c_comp = 13 if comp else 0
    c_dif = 20 if dif else 0
    c_mes = max(0, 100 - (2.5 * meses))
    c_md = max(0, (md - 2) * 1.42)
    pontos = c_comp + c_dif + c_mes + c_md
    prob = min(95.0, (pontos / 103.0) * 33.0)
    return prob, {"Base": 0, "Compressão": c_comp, "Defeito Difuso": c_dif, "Sintomas (Meses)": c_mes, "Mean Defect": c_md}

def risco_recorrencia_cushing_cuper_2025(meses, hardy, local, previa):
    c_mes = meses * 0.41
    c_har = hardy * 12.5
    c_prev = 28 if previa else 0
    c_loc = {'direita': 14, 'central': 18, 'esquerda': 22, 'haste': 33}.get(local.lower(), 0)
    pontos = c_mes + c_har + c_prev + c_loc
    prob = (pontos/60)*10 if pontos <= 60 else min(95.0, 10 + (pontos-60)*0.75)
    return prob, {"Base": 0, "Duração Sintomas": c_mes, "Grau Hardy": c_har, "Cirurgia Prévia": c_prev, "Localização": c_loc}

# ==========================================
# GESTÃO DE DADOS (SQLITE)
# ==========================================
def obter_classificacao(prob, tipo):
    if tipo == "melhora":
        return ("Alta Chance", "green") if prob >= 60 else ("Chance Moderada", "orange") if prob >= 30 else ("Baixa Chance", "red")
    return ("Baixo Risco", "green") if prob < 15 else ("Risco Moderado", "orange") if prob < 30 else ("Alto Risco", "red")

def salvar_registro(mod, prob, tipo, parametros=""):
    pac = st.session_state.paciente_ativo['nome']
    mae = st.session_state.paciente_ativo['mae']
    pront = str(st.session_state.paciente_ativo['prontuario'])
    classif, _ = obter_classificacao(prob, tipo)
    data = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        INSERT INTO avaliacoes (data_hora, prontuario, paciente, mae, avaliacao_clinica, parametros, resultado, classificacao, tipo)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (data, pront, pac, mae, mod, parametros, round(prob, 1), classif, tipo))
    conn.commit()
    conn.close()
    return True

def obter_df_paciente(prontuario):
    conn = sqlite3.connect(DB_NAME)
    query = '''
        SELECT data_hora as "Data/Hora", avaliacao_clinica as "Avaliação Clínica", parametros as "Parâmetros Inseridos", 
               resultado as "Resultado (%)", classificacao as "Classificação", tipo as "Tipo"
        FROM avaliacoes WHERE prontuario = ?
    '''
    df = pd.read_sql(query, conn, params=(str(prontuario),))
    conn.close()
    return df

def obter_df_completo():
    conn = sqlite3.connect(DB_NAME)
    query = '''
        SELECT data_hora as "Data/Hora", prontuario as "Prontuário", paciente as "Paciente", mae as "Mãe",
               avaliacao_clinica as "Avaliação Clínica", parametros as "Parâmetros Inseridos", 
               resultado as "Resultado (%)", classificacao as "Classificação", tipo as "Tipo"
        FROM avaliacoes
    '''
    df = pd.read_sql(query, conn)
    conn.close()
    return df

# ==========================================
# ESTILOS CSS INTELIGENTES (DARK/LIGHT MODE)
# ==========================================
st.markdown("""
<style>
    .login-box { background-color: var(--secondary-background-color); border-radius: 24px; border: 1px solid rgba(128, 128, 128, 0.15); padding: 50px; box-shadow: 0 15px 35px rgba(0, 0, 0, 0.15); text-align: center; max-width: 500px; margin: auto; color: var(--text-color); }
    .watermark { position: fixed; bottom: 20px; right: 30px; opacity: 0.5; font-family: 'Georgia', serif; font-style: italic; font-size: 0.9rem; pointer-events: none; color: var(--text-color); }
    .main-title { background: -webkit-linear-gradient(45deg, #1565c0, #b8860b); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-weight: 900; font-size: 3.5rem; text-align: center; letter-spacing: -1px; }
    .harvey-text { font-family: 'Georgia', serif; font-style: italic; color: #b8860b; margin-left: 10px; }
    .patient-header { background: linear-gradient(135deg, #0b2e59, #1565c0); color: white; padding: 25px 35px; border-radius: 20px; margin-bottom: 30px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 10px 30px rgba(11, 46, 89, 0.2); }
    .dashboard-card { background-color: var(--secondary-background-color); border-radius: 16px; padding: 24px; box-shadow: 0 8px 24px rgba(0,0,0,0.06); text-align: left; border-left: 8px solid #ddd; color: var(--text-color); transition: all 0.3s ease; display: flex; flex-direction: column; justify-content: space-between; }
    .dashboard-card:hover { transform: translateY(-4px); box-shadow: 0 12px 32px rgba(0,0,0,0.1); }
    .card-value { font-size: 2.5rem; font-weight: 800; margin: 10px 0; line-height: 1; }
    .b-green { border-left-color: #2e7d32 !important; } .t-green { color: #2e7d32 !important; }
    .b-orange { border-left-color: #ef6c00 !important; } .t-orange { color: #ef6c00 !important; }
    .b-red { border-left-color: #c62828 !important; } .t-red { color: #c62828 !important; }
    .input-card { background-color: var(--secondary-background-color); padding: 35px; border-radius: 20px; box-shadow: 0 8px 30px rgba(0,0,0,0.05); margin-top: 15px; color: var(--text-color); border: 1px solid rgba(128, 128, 128, 0.1); }
    .calc-info { background-color: rgba(21, 101, 192, 0.05); padding: 16px 20px; border-radius: 12px; border-left: 5px solid #1565c0; margin-bottom: 25px; font-size: 0.95rem; color: var(--text-color); box-shadow: 0 2px 10px rgba(0,0,0,0.02); }
    .sidebar-section-title { font-size: 0.75rem; font-weight: 700; color: #888; text-transform: uppercase; letter-spacing: 1.2px; margin-top: 20px; margin-bottom: 10px; }
    .sidebar-patient-card { background: rgba(21, 101, 192, 0.08); border-left: 4px solid #1565c0; padding: 15px; border-radius: 8px; margin-bottom: 15px; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# TELA DE LOGIN
# ==========================================
if not st.session_state.autenticado:
    st.markdown("<br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<div class='login-box'>", unsafe_allow_html=True)
        st.markdown("<h1 class='main-title' style='font-size: 2.8rem;'>NeuroPreditor <span class='harvey-text'>Harvey</span></h1>", unsafe_allow_html=True)
        st.markdown("<p style='font-size: 1rem; opacity: 0.8; margin-bottom: 30px;'>Acesso Restrito - Hospital Universitário Getúlio Vargas</p>", unsafe_allow_html=True)
        
        senha = st.text_input("Senha Institucional:", type="password", placeholder="Insira a senha...")
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("DESBLOQUEAR ACESSO", use_container_width=True):
            if senha == SENHA_CORRETA:
                st.session_state.autenticado = True
                st.rerun()
            else: 
                st.error("Senha incorreta. Tente novamente.")
        
        st.markdown("<hr style='opacity: 0.15; margin: 30px 0 20px 0;'>", unsafe_allow_html=True)
        st.markdown("<p style='font-size: 0.85rem; font-weight: 600; opacity: 0.7; margin: 0; text-transform: uppercase; letter-spacing: 1px;'>Made By Vinícius Bacelar Ferreira</p>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

# ==========================================
# NAVEGAÇÃO / MENU LATERAL 
# ==========================================
with st.sidebar:
    st.markdown("""
        <div style='text-align: center; padding: 10px 0;'>
            <h4 style='color: var(--text-color); margin: 0; font-weight: 600; opacity: 0.8;'>HUGV - UFAM</h4>
            <h2 style='color: #1565c0; margin: 5px 0 15px 0; font-weight: 800; letter-spacing: -0.5px;'>Harvey<span style='color: #b8860b;'></span></h2>
        </div>
    """, unsafe_allow_html=True)
    st.markdown("<hr style='margin: 0; opacity: 0.2;'>", unsafe_allow_html=True)
    
    st.markdown("<div class='sidebar-section-title'>Navegação Principal</div>", unsafe_allow_html=True)
    nav = st.radio("Módulos:", ["🏠 Área de Trabalho", "📊 Gestão & Análise"], label_visibility="collapsed")
    st.markdown("<hr style='margin: 15px 0; opacity: 0.2;'>", unsafe_allow_html=True)
    
    if st.session_state.paciente_ativo['prontuario']:
        st.markdown("<div class='sidebar-section-title'>Paciente em Consulta</div>", unsafe_allow_html=True)
        st.markdown(f"""
        <div class="sidebar-patient-card">
            <div style="font-size: 0.8rem; color: var(--text-color); opacity: 0.7;">Prontuário: <b>{st.session_state.paciente_ativo['prontuario']}</b></div>
            <div style="font-weight: bold; font-size: 1.05rem; color: var(--text-color); margin-top: 5px; line-height: 1.2;">👤 {st.session_state.paciente_ativo['nome']}</div>
        </div>
        """, unsafe_allow_html=True)
        
        if st.button("❌ Fechar Prontuário", type="primary", use_container_width=True):
            st.session_state.paciente_ativo = {"nome": "", "mae": "", "prontuario": ""}
            for mod in lista_modulos:
                st.session_state[mod] = None
            st.rerun()
        st.markdown("<hr style='margin: 15px 0; opacity: 0.2;'>", unsafe_allow_html=True)

    st.markdown("<div class='sidebar-section-title'>Sistema</div>", unsafe_allow_html=True)
    with st.expander("🌓 Tema (Claro/Escuro)"):
        st.write("O sistema adapta-se automaticamente à preferência do seu dispositivo. Para alterar manualmente, clique no **Menu (⋮)** no canto superior direito da tela > **Settings** > **Theme**.")
    
    if st.button("🚪 Sair do Sistema", use_container_width=True):
        st.session_state.autenticado = False
        st.session_state.paciente_ativo = {"nome": "", "mae": "", "prontuario": ""}
        st.rerun()
        
    st.markdown("<br><br><p style='text-align: center; font-size: 0.75rem; font-weight: bold; opacity: 0.5;'>Made By Vinícius Bacelar Ferreira</p>", unsafe_allow_html=True)

# ==========================================
# ÁREA DE TRABALHO
# ==========================================
if nav == "🏠 Área de Trabalho":
    if not st.session_state.paciente_ativo['prontuario']:
        st.markdown("<h1 class='main-title'>NeuroPreditor Transesfenoidal <span class='harvey-text'>Harvey</span></h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; font-size: 1.15rem; opacity: 0.85; max-width: 900px; margin: 15px auto 35px auto;'>Um sistema avançado de apoio à decisão clínica e cirúrgica com XAI. Utiliza modelos preditivos matemáticos baseados na literatura científica recente para estimar prognósticos visuais e calcular os riscos de complicações perioperatórias em cirurgias de tumores hipofisários.</p>", unsafe_allow_html=True)
        
        st.markdown("<div class='input-card' style='text-align: center; padding: 25px;'><p style='font-size:1.15rem; font-style:italic;'>\"Gostaria de ver o dia em que alguém fosse nomeado cirurgião sem ter mãos, pois a parte operatória é a menor parte do trabalho.\"</p><p style='color:#b8860b; font-weight:800; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 0;'>— HARVEY WILLIAMS CUSHING</p></div>", unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("<div class='input-card'><h3>🔍 Acessar Prontuário Antigo</h3>", unsafe_allow_html=True)
            conn = sqlite3.connect(DB_NAME)
            df_b = pd.read_sql("SELECT DISTINCT prontuario as 'Prontuário', paciente as 'Paciente', mae as 'Mãe' FROM avaliacoes", conn)
            conn.close()
            
            if not df_b.empty:
                lista = [""] + [f"{r['Prontuário']} - {r['Paciente']}" for _, r in df_b.iterrows()]
                sel = st.selectbox("Selecione o paciente:", lista)
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("Abrir Prontuário Selecionado", use_container_width=True) and sel:
                    id_p = sel.split(" - ")[0]
                    dados = df_b[df_b['Prontuário'] == id_p].iloc[0]
                    st.session_state.paciente_ativo = {"prontuario": id_p, "nome": dados['Paciente'], "mae": dados['Mãe']}
                    st.rerun()
            else: st.info("Sem registros na base de dados no momento.")
            st.markdown("</div>", unsafe_allow_html=True)
            
        with c2:
            st.markdown("<div class='input-card'><h3>➕ Cadastrar Novo Paciente</h3>", unsafe_allow_html=True)
            nn = st.text_input("Nome Completo do Paciente:")
            nm = st.text_input("Nome da Mãe:")
            np = st.text_input("Número do Prontuário:")
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Cadastrar paciente", use_container_width=True) and nn and np:
                st.session_state.paciente_ativo = {"nome": nn, "mae": nm, "prontuario": str(np)}
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
            
    else:
        st.markdown(f"""
        <div class="patient-header">
            <div>
                <p style="font-size:0.85rem; opacity:0.8; margin-bottom:5px; text-transform:uppercase; letter-spacing: 1px;">Prontuário Eletrônico Ativo</p>
                <h2 style="margin-top:0; margin-bottom:0;">👤 {st.session_state.paciente_ativo["nome"]}</h2>
            </div>
            <div style="text-align: right;">
                <p style="margin-bottom:10px; font-size: 1.1rem;">Prontuário: <b>{st.session_state.paciente_ativo["prontuario"]}</b></p>
                <button style="background: rgba(255,255,255,0.2); border: 1px solid white; color: white; border-radius: 8px; padding: 6px 15px; cursor: pointer; transition: 0.3s;" onclick="window.location.reload();" onmouseover="this.style.background='rgba(255,255,255,0.4)'" onmouseout="this.style.background='rgba(255,255,255,0.2)'">Atualizar Ficha</button>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        tabs = st.tabs(["📊 Painel Visual", "👁️ Visão", "🔄 Cushing", "💧 Fístula LCR", "🚰 D.I.", "🧂 Sódio", "🦠 Meningite", "📈 Recidiva", "🧬 Acromegalia", "📉 NFPA", "📄 Relatório"])

        painel_placeholder = tabs[0].empty()
        relatorio_placeholder = tabs[10].empty()

        with tabs[1]: 
            st.markdown("<div class='calc-info'><b>O que calcula:</b> Estima a probabilidade de melhora visual ou recuperação do campo visual após a descompressão.</div>", unsafe_allow_html=True)
            st.markdown("<div class='input-card'><h4>👁️ Recuperação Visual</h4>", unsafe_allow_html=True)
            v1, v2 = st.columns(2)
            with v1: 
                v_q = st.toggle("Havia compressão do quiasma óptico?")
                v_d = st.toggle("Apresentava defeito campimétrico difuso?")
            with v2: 
                v_m = st.number_input("Duração dos sintomas visuais (meses):", 0)
                v_md = st.number_input("Mean Defect (MD) pré-operatório (dB):", 0.0)
            
            if st.button("Calcular e Salvar Probabilidade Visual", key="btn_visao"):
                res, contribs = risco_melhora_visual_ji_2023(v_q, v_d, v_m, v_md)
                params = f"Compressão: {'Sim' if v_q else 'Não'} | Defeito: {'Sim' if v_d else 'Não'} | Sintomas: {v_m} meses | MD: {v_md} dB"
                st.session_state.visao_res = (res, contribs)
                salvar_registro("Prognóstico Visual", res, "melhora", params)
            
            if st.session_state.visao_res is not None:
                res, contribs = st.session_state.visao_res
                st.success("Cálculo realizado e salvo com sucesso na base de dados!")
                
                col_g, col_x = st.columns([1, 1.5])
                with col_g:
                    st.plotly_chart(gerar_grafico_velocimetro(res, "melhora"), use_container_width=True)
                with col_x:
                    st.markdown("##### 🧠 Explicabilidade do Algoritmo (XAI)")
                    st.markdown(obter_texto_explicativo(contribs))
                    st.plotly_chart(gerar_grafico_waterfall(contribs), use_container_width=True)
                
            with st.expander("📚 Referência Científica"):
                st.markdown("**Ji X, Zhuang X, Yang S, et al.** Visual field improvement after endoscopic transsphenoidal surgery... *Front Oncol*. 2023;13:1108883.")
            st.markdown("</div>", unsafe_allow_html=True)
    
        with tabs[2]: 
            st.markdown("<div class='calc-info'><b>O que calcula:</b> Utiliza o Modelo CuPeR para prever o risco de persistência ou recorrência da Doença de Cushing.</div>", unsafe_allow_html=True)
            st.markdown("<div class='input-card'><h4>🔄 Doença de Cushing</h4>", unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            with c1: 
                c_dur = st.number_input("Duração dos sintomas antes da cirurgia (meses):", 0, key="c1")
                c_cp = st.toggle("O paciente possui cirurgia pituitária prévia?")
            with c2: 
                c_h = st.select_slider("Classificação de Invasão de Hardy:", [0,1,2,3,4], value=2)
                c_l = st.selectbox("Localização predominante do Tumor na RM:", ["Bilateral","Direita","Esquerda","Central","Haste"])
            
            if st.button("Calcular e Salvar Risco de Recorrência", key="btn_cushing"):
                res, contribs = risco_recorrencia_cushing_cuper_2025(c_dur, c_h, c_l, c_cp)
                params = f"Sintomas: {c_dur} meses | Cirurgia Prévia: {'Sim' if c_cp else 'Não'} | Grau Hardy: {c_h} | Localização: {c_l}"
                st.session_state.cushing_res = (res, contribs)
                salvar_registro("Recorrência Cushing", res, "risco", params)
            
            if st.session_state.cushing_res is not None:
                res, contribs = st.session_state.cushing_res
                st.success("Cálculo realizado e salvo com sucesso na base de dados!")
                
                col_g, col_x = st.columns([1, 1.5])
                with col_g:
                    st.plotly_chart(gerar_grafico_velocimetro(res, "risco"), use_container_width=True)
                with col_x:
                    st.markdown("##### 🧠 Explicabilidade do Algoritmo (XAI)")
                    st.markdown(obter_texto_explicativo(contribs))
                    st.plotly_chart(gerar_grafico_waterfall(contribs), use_container_width=True)
                
            with st.expander("📚 Referência Científica"):
                st.markdown("**Sharifi G, Paraandavaji E, et al.** The CuPeR model: A dynamic online tool... *J Clin Transl Endocrinol*. 2025;41:100417.")
            st.markdown("</div>", unsafe_allow_html=True)

        with tabs[3]: 
            st.markdown("<div class='calc-info'><b>O que calcula:</b> Avalia o risco de fístula liquórica (vazamento de LCR) tanto no período intraoperatório quanto no pós-operatório.</div>", unsafe_allow_html=True)
            st.markdown("<div class='input-card'><h4>💧 Fístula de Líquor</h4>", unsafe_allow_html=True)
            sub_tabs_fistula = st.tabs(["Fístula Intraoperatória (Cai et al.)", "Fístula Pós-operatória (Zhang et al.)"])
            
            with sub_tabs_fistula[0]:
                f_intra1, f_intra2 = st.columns(2)
                with f_intra1: f_altura = st.number_input("Altura máxima do Tumor na RM (mm):", 0.0)
                with f_intra2: f_albumina = st.number_input("Albumina Sérica pré-operatória (g/L):", 0.0, value=40.0)
                    
                if st.button("Calcular Fístula Intraoperatória", key="btn_fistula_intra"):
                    res, contribs = risco_fistula_intraop_cai_2021(f_altura, f_albumina)
                    params = f"Altura do Tumor: {f_altura} mm | Albumina Sérica: {f_albumina} g/L"
                    st.session_state.fistula_intra_res = (res, contribs)
                    salvar_registro("Fístula LCR (Intraop)", res, "risco", params)
                    
                if st.session_state.fistula_intra_res is not None:
                    res, contribs = st.session_state.fistula_intra_res
                    st.success("Cálculo intraoperatório salvo com sucesso!")
                    
                    col_g, col_x = st.columns([1, 1.5])
                    with col_g:
                        st.plotly_chart(gerar_grafico_velocimetro(res, "risco"), use_container_width=True)
                    with col_x:
                        st.markdown("##### 🧠 Explicabilidade do Algoritmo (XAI)")
                        st.markdown(obter_texto_explicativo(contribs))
                        st.plotly_chart(gerar_grafico_waterfall(contribs), use_container_width=True)

            with sub_tabs_fistula[1]:
                f1, f2 = st.columns(2)
                with f1: 
                    f_k = st.toggle("Grau de Kelly intraoperatório ≥ 2?")
                    f_s = st.toggle("Extensão suprasselar do tumor ≥ Grau B?")
                with f2: 
                    f_p = st.toggle("Pneumoencéfalo pós-operatório ≥ Grau 3 na TC?")
                    f_j = st.number_input("Tamanho estimado da janela óssea selar (mm):", 0.0)
                
                if st.button("Calcular Fístula Pós-operatória", key="btn_fistula_pos"):
                    res, contribs = risco_fistula_lcr_zhang_2025(f_k, f_s, f_p, f_j)
                    params = f"Kelly ≥ 2: {'Sim' if f_k else 'Não'} | Supra ≥ B: {'Sim' if f_s else 'Não'} | Pneumoencéfalo ≥ 3: {'Sim' if f_p else 'Não'} | Janela óssea: {f_j} mm"
                    st.session_state.fistula_res = (res, contribs)
                    salvar_registro("Risco Fístula LCR", res, "risco", params)

                if st.session_state.fistula_res is not None:
                    res, contribs = st.session_state.fistula_res
                    st.success("Cálculo pós-operatório salvo com sucesso!")
                    
                    col_g, col_x = st.columns([1, 1.5])
                    with col_g:
                        st.plotly_chart(gerar_grafico_velocimetro(res, "risco"), use_container_width=True)
                    with col_x:
                        st.markdown("##### 🧠 Explicabilidade do Algoritmo (XAI)")
                        st.markdown(obter_texto_explicativo(contribs))
                        st.plotly_chart(gerar_grafico_waterfall(contribs), use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)

        with tabs[4]: 
            st.markdown("<div class='calc-info'><b>O que calcula:</b> Prediz a probabilidade de desenvolver Diabetes Insipidus central no pós-operatório.</div>", unsafe_allow_html=True)
            st.markdown("<div class='input-card'><h4>🚰 Diabetes Insipidus</h4>", unsafe_allow_html=True)
            d1, d2 = st.columns(2)
            with d1: 
                di_d = st.checkbox("O paciente possui Diabetes Mellitus prévio?")
                di_h = st.checkbox("O paciente possui Hipertensão Arterial Sistêmica?")
                di_ca = st.checkbox("O paciente possui Cardiopatia prévia?")
            with d2: 
                di_co = st.number_input("Nível de Cortisol basal pré-operatório (mmol/L):", 0.0)
                di_f = st.toggle("Apresentou fístula liquórica documentada no pós-operatório?")
                di_r = st.toggle("A textura do tumor era firme/rígida na avaliação intraoperatória?")
            
            if st.button("Calcular e Salvar Risco de D.I.", key="btn_di"):
                res, contribs = risco_diabetes_insipidus_li_2024(di_d, di_h, di_ca, di_co, di_f, di_r)
                params = f"DM: {'Sim' if di_d else 'Não'} | HAS: {'Sim' if di_h else 'Não'} | Cardiopatia: {'Sim' if di_ca else 'Não'} | Cortisol pré-op: {di_co} | Fístula: {'Sim' if di_f else 'Não'} | Tumor Rígido: {'Sim' if di_r else 'Não'}"
                st.session_state.di_res = (res, contribs)
                salvar_registro("Diabetes Insipidus", res, "risco", params)
                
            if st.session_state.di_res is not None:
                res, contribs = st.session_state.di_res
                st.success("Cálculo realizado e salvo com sucesso!")
                
                col_g, col_x = st.columns([1, 1.5])
                with col_g:
                    st.plotly_chart(gerar_grafico_velocimetro(res, "risco"), use_container_width=True)
                with col_x:
                    st.markdown("##### 🧠 Explicabilidade do Algoritmo (XAI)")
                    st.markdown(obter_texto_explicativo(contribs))
                    st.plotly_chart(gerar_grafico_waterfall(contribs), use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)

        with tabs[5]: 
            st.markdown("<div class='calc-info'><b>O que calcula:</b> Risco de Hiponatremia Tardia (DPH) ocorrendo na fase secundária de SIADH.</div>", unsafe_allow_html=True)
            st.markdown("<div class='input-card'><h4>🧂 Hiponatremia Tardia (DPH)</h4>", unsafe_allow_html=True)
            mod_h = st.radio("Selecione a base do modelo preditivo:", ["Modelo de Sangue (Cai et al.)", "Modelo de Imagem/Hormonal (Tan et al.)"])
            hp12 = st.toggle("Houve queda do Sódio sérico nos Dias 1 e 2 pós-op?")
            
            if mod_h == "Modelo de Sangue (Cai et al.)":
                mo = st.number_input("Porcentagem de Monócitos no hemograma (%):", 0.0)
                pt = st.number_input("Tempo de Protrombina (segundos):", 0.0)
                if st.button("Calcular e Salvar Risco", key="btn_hipo_cai"):
                    res, contribs = risco_pdh_cai_2023(hp12, mo, pt)
                    params = f"Queda Sódio D1-D2: {'Sim' if hp12 else 'Não'} | Monócitos: {mo}% | PT: {pt} seg"
                    st.session_state.hipo_res = (res, contribs)
                    salvar_registro("DPH (Modelo Cai)", res, "risco", params)
            else:
                pr = st.number_input("Nível de Prolactina basal pré-op (ng/mL):", 0.0)
                dia = st.number_input("Elevação estimada do Diafragma Selar (mm):", 0.0)
                if st.button("Calcular e Salvar Risco", key="btn_hipo_tan"):
                    res, contribs = risco_pdh_tan_2025(pr, dia, hp12)
                    params = f"Queda Sódio D1-D2: {'Sim' if hp12 else 'Não'} | Prolactina: {pr} | Diafragma: {dia} mm"
                    st.session_state.hipo_res = (res, contribs)
                    salvar_registro("DPH (Modelo Tan)", res, "risco", params)
                    
            if st.session_state.hipo_res is not None:
                res, contribs = st.session_state.hipo_res
                st.success("Cálculo realizado e salvo com sucesso!")
                
                col_g, col_x = st.columns([1, 1.5])
                with col_g:
                    st.plotly_chart(gerar_grafico_velocimetro(res, "risco"), use_container_width=True)
                with col_x:
                    st.markdown("##### 🧠 Explicabilidade do Algoritmo (XAI)")
                    st.markdown(obter_texto_explicativo(contribs))
                    st.plotly_chart(gerar_grafico_waterfall(contribs), use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)

        with tabs[6]: 
            st.markdown("<div class='calc-info'><b>O que calcula:</b> Estima o risco de meningite bacteriana pós-operatória.</div>", unsafe_allow_html=True)
            st.markdown("<div class='input-card'><h4>🦠 Meningite Pós-operatória</h4>", unsafe_allow_html=True)
            m1, m2 = st.columns(2)
            with m1: 
                md = st.number_input("Duração total da Cirurgia (horas):", 0.0)
                mf = st.toggle("Houve fístula de LCR identificada intraoperatória?")
            with m2: 
                mt = st.number_input("Diâmetro máximo do Tumor na RM (cm):", 0.0)
            
            if st.button("Calcular e Salvar Risco de Meningite", key="btn_meningite"):
                res, contribs = risco_meningite_zhou_2025(md, mt, mf)
                params = f"Duração Cirurgia: {md} horas | Diâmetro do Tumor: {mt} cm | Fístula Intraop: {'Sim' if mf else 'Não'}"
                st.session_state.meningite_res = (res, contribs)
                salvar_registro("Risco Meningite", res, "risco", params)
                
            if st.session_state.meningite_res is not None:
                res, contribs = st.session_state.meningite_res
                st.success("Cálculo realizado e salvo com sucesso!")
                
                col_g, col_x = st.columns([1, 1.5])
                with col_g:
                    st.plotly_chart(gerar_grafico_velocimetro(res, "risco"), use_container_width=True)
                with col_x:
                    st.markdown("##### 🧠 Explicabilidade do Algoritmo (XAI)")
                    st.markdown(obter_texto_explicativo(contribs))
                    st.plotly_chart(gerar_grafico_waterfall(contribs), use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)
            
        with tabs[7]: 
            st.markdown("<div class='calc-info'><b>O que calcula:</b> Estima o risco de <b>recorrência ou progressão (5 anos)</b> para macroadenomas e adenomas gigantes.</div>", unsafe_allow_html=True)
            st.markdown("<div class='input-card'><h4>📈 Recidiva (Gigantes)</h4>", unsafe_allow_html=True)
            ch1, ch2 = st.columns(2)
            with ch1:
                chen_res_op = st.selectbox("Extensão da Ressecção Cirúrgica:", ["Ressecção Total (GTR > 95%)", "Ressecção Quase Total (NTR 90-95%)", "Ressecção Subtotal (STR 70-90%)", "Ressecção Parcial (PR < 70%)"])
                chen_knosp = st.selectbox("Classificação de Knosp (RM Pré-op):", ["Graus 0 - 1", "Graus 2 - 3", "Grau 4"])
                chen_tabagismo = st.toggle("O paciente possui histórico de tabagismo?")
            with ch2:
                chen_ki67 = st.toggle("Índice de proliferação tumoral Ki-67 ≥ 3%?")
                chen_bmi = st.toggle("Índice de Massa Corporal (IMC) ≥ 25 kg/m²?")
                
            if st.button("Calcular e Salvar Risco de Recidiva", key="btn_chen"):
                res, contribs = risco_progressao_chen_2021(chen_res_op, chen_knosp, chen_ki67, chen_bmi, chen_tabagismo)
                params = f"Ressecção: {chen_res_op} | Knosp: {chen_knosp} | Ki-67 ≥3%: {'Sim' if chen_ki67 else 'Não'} | IMC ≥25: {'Sim' if chen_bmi else 'Não'} | Tabaco: {'Sim' if chen_tabagismo else 'Não'}"
                st.session_state.chen_res = (res, contribs)
                salvar_registro("Risco Recidiva 5 Anos", res, "risco", params)
                
            if st.session_state.chen_res is not None:
                res, contribs = st.session_state.chen_res
                st.success("Cálculo realizado e salvo com sucesso!")
                
                col_g, col_x = st.columns([1, 1.5])
                with col_g:
                    st.plotly_chart(gerar_grafico_velocimetro(res, "risco"), use_container_width=True)
                with col_x:
                    st.markdown("##### 🧠 Explicabilidade do Algoritmo (XAI)")
                    st.markdown(obter_texto_explicativo(contribs))
                    st.plotly_chart(gerar_grafico_waterfall(contribs), use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)
            
        with tabs[8]: 
            st.markdown("<div class='calc-info'><b>O que calcula:</b> Probabilidade de <b>Remissão Bioquímica a longo prazo</b> em adenomas secretores de GH.</div>", unsafe_allow_html=True)
            st.markdown("<div class='input-card'><h4>🧬 Acromegalia (Remissão)</h4>", unsafe_allow_html=True)
            ac1, ac2 = st.columns(2)
            with ac1:
                acro_idade = st.number_input("Idade do paciente no diagnóstico (anos):", 0)
                acro_diam = st.number_input("Diâmetro máximo do tumor na RM (cm):", 0.0, step=0.1)
                acro_knosp = st.selectbox("Classificação de Knosp:", ["Grau 0", "Grau 1", "Grau 2", "Grau 3A", "Grau 3B", "Grau 4"])
            with ac2:
                acro_igf1 = st.number_input("Índice de IGF-1 basal pré-operatório:", 0.0, step=0.1)
                acro_gh = st.number_input("Nível de GH basal no diagnóstico (ng/mL):", 0.0, step=0.1)
                
            if st.button("Calcular Probabilidade de Remissão", key="btn_acro"):
                res, contribs = remissao_acromegalia_cohen_2024(acro_idade, acro_diam, acro_knosp, acro_igf1, acro_gh)
                params = f"Idade: {acro_idade} | Diâmetro: {acro_diam} | Knosp: {acro_knosp} | IGF-1: {acro_igf1} | GH: {acro_gh}"
                st.session_state.acro_res = (res, contribs)
                salvar_registro("Remissão Bioquímica (Acromegalia)", res, "melhora", params)
                
            if st.session_state.acro_res is not None:
                res, contribs = st.session_state.acro_res
                st.success("Cálculo realizado e salvo com sucesso!")
                
                col_g, col_x = st.columns([1, 1.5])
                with col_g:
                    st.plotly_chart(gerar_grafico_velocimetro(res, "melhora"), use_container_width=True)
                with col_x:
                    st.markdown("##### 🧠 Explicabilidade do Algoritmo (XAI)")
                    st.markdown(obter_texto_explicativo(contribs))
                    st.plotly_chart(gerar_grafico_waterfall(contribs), use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)

        with tabs[9]:
            st.markdown("<div class='calc-info'><b>O que calcula:</b> Risco de <b>recorrência ou progressão tumoral</b> a longo prazo para pacientes do <b>sexo masculino</b> com NFPA.</div>", unsafe_allow_html=True)
            st.markdown("<div class='input-card'><h4>📉 Recidiva em NFPA (Homens)</h4>", unsafe_allow_html=True)
            nf1, nf2 = st.columns(2)
            with nf1:
                nfpa_knosp = st.toggle("A Classificação de Knosp Modificada é Grau 3B ou 4?")
                nfpa_ki67 = st.toggle("O Índice de proliferação Ki-67 é ≥ 3%?")
            with nf2:
                nfpa_res = st.selectbox("Extensão da Ressecção Cirúrgica:", ["Ressecção Total (GTR)", "Ressecção Subtotal/Parcial (STR/PR)"])
                
            if st.button("Calcular Risco de Recidiva (NFPA)", key="btn_nfpa"):
                resseccao_subtotal = True if nfpa_res == "Ressecção Subtotal/Parcial (STR/PR)" else False
                res, contribs = risco_progressao_nfpa_zhong_2024(nfpa_ki67, nfpa_knosp, resseccao_subtotal)
                params = f"Knosp 3B-4: {'Sim' if nfpa_knosp else 'Não'} | Ki-67 ≥3%: {'Sim' if nfpa_ki67 else 'Não'} | Ressecção: {nfpa_res}"
                st.session_state.nfpa_res = (res, contribs)
                salvar_registro("Recidiva NFPA (Homens)", res, "risco", params)
                
            if st.session_state.nfpa_res is not None:
                res, contribs = st.session_state.nfpa_res
                st.success("Cálculo realizado e salvo com sucesso!")
                
                col_g, col_x = st.columns([1, 1.5])
                with col_g:
                    st.plotly_chart(gerar_grafico_velocimetro(res, "risco"), use_container_width=True)
                with col_x:
                    st.markdown("##### 🧠 Explicabilidade do Algoritmo (XAI)")
                    st.markdown(obter_texto_explicativo(contribs))
                    st.plotly_chart(gerar_grafico_waterfall(contribs), use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)

        # =======================================================
        # PREENCHIMENTO DOS PLACEHOLDERS (ATUALIZAÇÃO DINÂMICA DA BASE DE DADOS)
        # =======================================================
        with painel_placeholder.container():
            st.subheader("📊 Resultados Consolidados e Arquivados")
            df_p = obter_df_paciente(st.session_state.paciente_ativo['prontuario'])
            if not df_p.empty:
                df_l = df_p.sort_values(by="Data/Hora").groupby("Avaliação Clínica").last().reset_index()
                cols = st.columns(3)
                for i, r in df_l.iterrows():
                    v = float(r['Resultado (%)'])
                    _, cor = obter_classificacao(v, r['Tipo'])
                    with cols[i % 3]:
                        st.markdown(f"""
                        <div class="dashboard-card b-{cor}">
                            <div>
                                <div style="font-weight:700; opacity:0.8; font-size: 0.95rem; text-transform: uppercase; letter-spacing: 0.5px;">{r["Avaliação Clínica"]}</div>
                                <div class="card-value t-{cor}">{v}%</div>
                            </div>
                            <div>
                                <div style="font-weight:bold; font-size: 1.1rem;" class="t-{cor}">{r["Classificação"]}</div>
                                <div style="font-size:0.8rem; opacity:0.6; margin-top: 8px;">{r["Data/Hora"]}</div>
                            </div>
                        </div><br>
                        """, unsafe_allow_html=True)
            else: 
                st.info("Nenhum cálculo salvo ainda. Realize as avaliações nas abas acima.")
                    
        with relatorio_placeholder.container():
            st.markdown("### 🖨️ Relatório Oficial (Formato A4)")
            linhas_html = ""
            df_rel_pac = obter_df_paciente(st.session_state.paciente_ativo['prontuario'])
            
            if not df_rel_pac.empty:
                df_latest_rel = df_rel_pac.sort_values(by="Data/Hora").groupby("Avaliação Clínica").last().reset_index()
                for _, r in df_latest_rel.iterrows():
                    param_str = r.get("Parâmetros Inseridos", "-")
                    if pd.isna(param_str): param_str = "-"
                    linhas_html += f"""
                    <tr>
                        <td style="font-weight: bold; color: #0b2e59;">{r['Avaliação Clínica']}</td>
                        <td style="font-size: 12px; color: #555;">{param_str}</td>
                        <td style="font-weight: bold; text-align: center; color: #333;">{r['Resultado (%)']}%</td>
                        <td style="text-align: center; color: #333;">{r['Classificação']}</td>
                    </tr>
                    """
            
            html_relatorio = f"""
            <html>
            <head>
            <style>
                body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background: transparent; margin: 0; padding: 20px; display: flex; justify-content: center; }}
                .print-button {{ background: #0b2e59; color: white; border: none; padding: 12px 25px; border-radius: 8px; font-weight: bold; font-size: 16px; cursor: pointer; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); width: 100%; transition: 0.3s; }}
                .print-button:hover {{ background: #1565c0; }}
                .a4-page {{ width: 210mm; min-height: 297mm; background: white; padding: 20mm; box-sizing: border-box; box-shadow: 0 10px 25px rgba(0,0,0,0.1); position: relative; color: black; border-radius: 5px; }}
                .header {{ border-bottom: 3px solid #0b2e59; padding-bottom: 15px; margin-bottom: 25px; text-align: center; }}
                .header h1 {{ margin: 0; color: #0b2e59; font-size: 26px; text-transform: uppercase; font-weight: 900; letter-spacing: -1px; }}
                .header h3 {{ margin: 5px 0 0 0; color: #777; font-size: 14px; font-weight: normal; letter-spacing: 1px; }}
                .patient-box {{ background: #f8f9fa; border-left: 4px solid #0b2e59; padding: 15px 20px; border-radius: 0 8px 8px 0; margin-bottom: 30px; }}
                .patient-box p {{ margin: 5px 0; font-size: 14px; color: #333; }}
                .section-title {{ font-size: 18px; color: #0b2e59; border-bottom: 2px solid #eee; padding-bottom: 5px; margin-bottom: 15px; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px; }}
                table {{ width: 100%; border-collapse: collapse; margin-bottom: 30px; }}
                th, td {{ border-bottom: 1px solid #eee; padding: 14px 12px; font-size: 13px; }}
                th {{ background-color: #0b2e59; color: white; text-align: center; font-weight: bold; text-transform: uppercase; font-size: 12px; letter-spacing: 0.5px; }}
                .footer {{ position: absolute; bottom: 20mm; left: 20mm; right: 20mm; border-top: 1px solid #ddd; padding-top: 15px; text-align: center; font-size: 11px; color: #777; }}
                @media print {{ body {{ background: white; padding: 0; display: block; }} .no-print {{ display: none !important; }} .a4-page {{ width: 100%; height: auto; padding: 0; box-shadow: none; border: none; margin: 0; }} }}
            </style>
            </head>
            <body>
                <div style="width: 210mm; max-width: 100%;">
                    <div class="no-print"><button class="print-button" onclick="window.print()">🖨️ CLIQUE AQUI PARA IMPRIMIR OU SALVAR EM PDF</button></div>
                    <div class="a4-page">
                        <div class="header">
                            <h1>Hospital Universitário Getúlio Vargas</h1>
                            <h3>NeuroPreditor Harvey - Relatório de Avaliação Preditiva</h3>
                        </div>
                        <div class="patient-box">
                            <p><b>Paciente:</b> {st.session_state.paciente_ativo['nome']}</p>
                            <p><b>Registro / Prontuário:</b> {st.session_state.paciente_ativo['prontuario']}</p>
                            <p><b>Nome da Mãe:</b> {st.session_state.paciente_ativo['mae']}</p>
                            <p><b>Data da Emissão:</b> {datetime.datetime.now().strftime("%d/%m/%Y às %H:%M")}</p>
                        </div>
                        <div class="section-title">Sumário de Risco e Parâmetros Analisados</div>
                        <table>
                            <tr>
                                <th style="width: 25%;">Módulo Clínico</th>
                                <th style="width: 45%;">Parâmetros Inseridos</th>
                                <th style="width: 12%;">Resultado</th>
                                <th style="width: 18%;">Classificação</th>
                            </tr>
                            {linhas_html if linhas_html else '<tr><td colspan="4" style="text-align:center; color: #333; padding: 20px;">Nenhuma avaliação realizada até o momento.</td></tr>'}
                        </table>
                        <div class="footer">
                            <p style="margin: 0; font-weight: bold; color: #333;">NeuroPreditor Harvey • HUGV - UFAM</p>
                            <p style="margin: 5px 0 0 0; font-style: italic;">Made By Vinícius Bacelar Ferreira</p>
                        </div>
                    </div>
                </div>
            </body>
            </html>
            """
            components.html(html_relatorio, height=1200, scrolling=True)

# ==========================================
# GESTÃO & ANALYTICS (DASHBOARD)
# ==========================================
elif nav == "📊 Gestão & Analytics":
    st.title("📊 Painel de Analytics do Serviço")
    df_g = obter_df_completo()
    
    if not df_g.empty:
        # Extração de Métricas com Regex
        med_idade, med_diam = extrair_metricas_parametros(df_g)
        total_pacientes = df_g['Prontuário'].nunique()
        total_avaliacoes = len(df_g)
        perc_alto_risco = (len(df_g[df_g['Classificação'] == 'Alto Risco']) / total_avaliacoes) * 100 if total_avaliacoes > 0 else 0
        
        # Exibição de Métricas (KPIs)
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total de Pacientes", total_pacientes)
        col2.metric("Total de Avaliações", total_avaliacoes)
        col3.metric("Média de Idades", f"{med_idade:.1f} anos" if med_idade > 0 else "N/A")
        col4.metric("Diâmetro Tumoral Médio", f"{med_diam:.1f} cm" if med_diam > 0 else "N/A")
        
        st.markdown("<hr style='opacity: 0.2;'>", unsafe_allow_html=True)
        
        # Gráficos
        chart_col1, chart_col2 = st.columns(2)
        
        with chart_col1:
            # Pie Chart de Classificação
            dist_class = df_g['Classificação'].value_counts()
            fig_pie = go.Figure(data=[go.Pie(labels=dist_class.index, values=dist_class.values, hole=.4, 
                                             marker_colors=['#2e7d32', '#ef6c00', '#c62828', '#1565c0'])])
            fig_pie.update_layout(title="Distribuição Geral de Risco/Prognóstico", paper_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig_pie, use_container_width=True)
            
        with chart_col2:
            # Bar Chart por Mês
            df_g['Mês'] = pd.to_datetime(df_g['Data/Hora'], format='%d/%m/%Y %H:%M').dt.strftime('%m/%Y')
            dist_mes = df_g['Mês'].value_counts().sort_index()
            fig_bar = go.Figure(data=[go.Bar(x=dist_mes.index, y=dist_mes.values, marker_color='#1565c0')])
            fig_bar.update_layout(title="Volume de Avaliações por Mês", xaxis_title="Mês", yaxis_title="Quantidade de Avaliações", paper_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig_bar, use_container_width=True)

        st.markdown("---")
        st.subheader("🗃️ Base de Dados Completa")
        st.dataframe(df_g.sort_values(by="Data/Hora", ascending=False).drop(columns=['Mês']), use_container_width=True, hide_index=True)
        st.download_button("📥 Exportar Base de Dados (CSV)", df_g.to_csv(index=False).encode('utf-8'), "historico_harvey_db.csv", "text/csv")
        
        st.markdown("---")
        st.subheader("🗑️ Excluir Registro do Sistema")
        
        conn = sqlite3.connect(DB_NAME)
        df_unicos = pd.read_sql("SELECT DISTINCT prontuario, paciente FROM avaliacoes", conn)
        conn.close()
        
        lista_d = [""] + [f"{r['prontuario']} - {r['paciente']}" for _, r in df_unicos.iterrows()]
        del_sel = st.selectbox("Selecione o paciente para apagar permanentemente:", lista_d)
        
        if st.button("🚨 CONFIRMAR EXCLUSÃO") and del_sel:
            id_d = del_sel.split(" - ")[0]
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute("DELETE FROM avaliacoes WHERE prontuario = ?", (id_d,))
            conn.commit()
            conn.close()
            st.success("Registro removido com sucesso da base de dados SQLite."); st.rerun()
    else: 
        st.info("Nenhum dado registrado na base de dados.")

st.markdown("<div class='watermark'>Made By Vinícius Bacelar Ferreira</div>", unsafe_allow_html=True)
