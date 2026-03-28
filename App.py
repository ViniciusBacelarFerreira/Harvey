import streamlit as st
import streamlit.components.v1 as components
import math
import pandas as pd
import datetime
import os

# ==========================================
# CONFIGURAÇÃO INICIAL E ESTADO DA SESSÃO
# ==========================================
st.set_page_config(page_title="NeuroPreditor Harvey", layout="wide", page_icon="🧠")

if 'autenticado' not in st.session_state:
    st.session_state.autenticado = False
if 'paciente_ativo' not in st.session_state:
    st.session_state.paciente_ativo = {"nome": "", "mae": "", "prontuario": ""}

# Variáveis para armazenar o resultado atual na tela sem recarregar a página
for mod in ['visao_res', 'cushing_res', 'fistula_res', 'di_res', 'hipo_res', 'meningite_res', 'chen_res', 'acro_res']:
    if mod not in st.session_state:
        st.session_state[mod] = None

ARQUIVO_CSV = "registro_pacientes.csv"
SENHA_CORRETA = "hugv1869"

# ==========================================
# FUNÇÕES DE CÁLCULO (BACK-END)
# ==========================================
def remissao_acromegalia_cohen_2024(idade, diametro, knosp, igf1, gh):
    pontos = 0
    if idade <= 50: pontos += 1
    if diametro >= 1.5: pontos += 1
    if knosp in ["Grau 3A", "Grau 3B", "Grau 4"]: pontos += 3
    if igf1 >= 3.0: pontos += 2
    if gh >= 8.0: pontos += 1
    
    # Conversão baseada no "Chance of Remission" (Figure 4 - Cohen-Cohen 2024)
    mapa_remissao = {0: 100.0, 1: 90.0, 2: 65.0, 3: 35.0, 4: 15.0, 5: 15.0}
    return mapa_remissao.get(pontos, 0.0) # Scores 6 a 8 têm ~0% de chance cirúrgica isolada

def risco_progressao_chen_2021(resection, knosp, ki67, bmi, tabagismo):
    pontos = 0
    if resection == "Ressecção Parcial (PR < 70%)": pontos += 10.0
    elif resection == "Ressecção Subtotal (STR 70-90%)": pontos += 5.5
    elif resection == "Ressecção Quase Total (NTR 90-95%)": pontos += 3.5
    if knosp == "Grau 4": pontos += 7.5
    elif knosp == "Graus 2 - 3": pontos += 3.8
    if ki67: pontos += 8.0
    if bmi: pontos += 4.0
    if tabagismo: pontos += 6.2
    logit = -4.0 + (0.2 * pontos)
    return (1 / (1 + math.exp(-logit))) * 100

def risco_meningite_zhou_2025(duracao_h, diametro_cm, fistula_intra):
    beta_duracao, beta_diametro, beta_fistula = 0.98, 0.99, 2.22
    beta_0 = -7.50 
    x_fistula = 1 if fistula_intra else 0
    logit = beta_0 + (beta_duracao * duracao_h) + (beta_diametro * diametro_cm) + (beta_fistula * x_fistula)
    return (1 / (1 + math.exp(-logit))) * 100

def risco_pdh_cai_2023(hipo_precoce, monocitos, pt):
    logit = -12.50 + (0.97 * (1 if hipo_precoce else 0)) + (0.20 * monocitos) + (0.58 * pt)
    return (1 / (1 + math.exp(-logit))) * 100

def risco_fistula_lcr_zhang_2025(kelly, supra, pneumo, janela):
    logit = -10.00 + (1.55*kelly) + (1.77*supra) + (2.56*pneumo) + (0.18*janela)
    return (1 / (1 + math.exp(-logit))) * 100

def risco_diabetes_insipidus_li_2024(dm, has, cardio, cortisol, fistula, rigido):
    logit = -6.50 + (0.845*dm) + (0.672*has) + (1.039*cardio) + (0.001*cortisol) + (1.121*fistula) + (0.776*rigido)
    return (1 / (1 + math.exp(-logit))) * 100

def risco_melhora_visual_ji_2023(comp, dif, meses, md):
    pontos = (13 if comp else 0) + (20 if dif else 0) + max(0, 100 - (2.5 * meses)) + max(0, (md - 2) * 1.42)
    return min(95.0, (pontos / 103.0) * 33.0)

def risco_recorrencia_cushing_cuper_2025(meses, hardy, local, previa):
    pontos = (meses * 0.41) + (hardy * 12.5) + (28 if previa else 0)
    loc_map = {'direita': 14, 'central': 18, 'esquerda': 22, 'haste': 33}
    pontos += loc_map.get(local.lower(), 0)
    if pontos <= 60: return (pontos/60)*10
    return min(95.0, 10 + (pontos-60)*0.75)

# ==========================================
# GESTÃO DE DADOS
# ==========================================
def obter_classificacao(prob, tipo):
    if tipo == "melhora":
        return ("Alta Chance", "green") if prob >= 60 else ("Chance Moderada", "orange") if prob >= 30 else ("Baixa Chance", "red")
    return ("Baixo Risco", "green") if prob < 15 else ("Risco Moderado", "orange") if prob < 30 else ("Alto Risco", "red")

def salvar_registro(mod, prob, tipo, parametros=""):
    pac, mae, pront = st.session_state.paciente_ativo['nome'], st.session_state.paciente_ativo['mae'], str(st.session_state.paciente_ativo['prontuario'])
    classif, _ = obter_classificacao(prob, tipo)
    data = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    
    novo = pd.DataFrame([{
        "Data/Hora": data, "Prontuário": pront, "Paciente": pac, "Mãe": mae, 
        "Avaliação Clínica": mod, "Parâmetros Inseridos": parametros,
        "Resultado (%)": round(prob, 1), "Classificação": classif, "Tipo": tipo
    }])
    
    if os.path.exists(ARQUIVO_CSV):
        df_e = pd.read_csv(ARQUIVO_CSV, dtype={'Prontuário': str})
        if 'Parâmetros Inseridos' not in df_e.columns:
            df_e['Parâmetros Inseridos'] = "Dados antigos não registrados"
        pd.concat([df_e, novo], ignore_index=True).to_csv(ARQUIVO_CSV, index=False, encoding='utf-8')
    else: 
        novo.to_csv(ARQUIVO_CSV, index=False, encoding='utf-8')
    return True

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
# NAVEGAÇÃO / MENU LATERAL (NOVO DESIGN)
# ==========================================
with st.sidebar:
    st.markdown("""
        <div style='text-align: center; padding: 10px 0;'>
            <h4 style='color: var(--text-color); margin: 0; font-weight: 600; opacity: 0.8;'>HUGV - UFAM</h4>
            <h2 style='color: #1565c0; margin: 5px 0 15px 0; font-weight: 800; letter-spacing: -0.5px;'>Harvey<span style='color: #b8860b;'>AI</span></h2>
        </div>
    """, unsafe_allow_html=True)
    st.markdown("<hr style='margin: 0; opacity: 0.2;'>", unsafe_allow_html=True)
    
    st.markdown("<div class='sidebar-section-title'>Navegação Principal</div>", unsafe_allow_html=True)
    nav = st.radio("Módulos:", ["🏠 Área de Trabalho", "⚙️ Histórico Geral"], label_visibility="collapsed")
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
            for mod in ['visao_res', 'cushing_res', 'fistula_res', 'di_res', 'hipo_res', 'meningite_res', 'chen_res', 'acro_res']:
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
        st.markdown("<p style='text-align: center; font-size: 1.15rem; opacity: 0.85; max-width: 900px; margin: 15px auto 35px auto;'>Um sistema avançado de apoio à decisão clínica e cirúrgica. Utiliza modelos preditivos matemáticos baseados na literatura científica recente para estimar prognósticos visuais e calcular os riscos de complicações perioperatórias em cirurgias de tumores hipofisários.</p>", unsafe_allow_html=True)
        
        st.markdown("<div class='input-card' style='text-align: center; padding: 25px;'><p style='font-size:1.15rem; font-style:italic;'>\"Gostaria de ver o dia em que alguém fosse nomeado cirurgião sem ter mãos, pois a parte operatória é a menor parte do trabalho.\"</p><p style='color:#b8860b; font-weight:800; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 0;'>— HARVEY WILLIAMS CUSHING</p></div>", unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("<div class='input-card'><h3>🔍 Acessar Prontuário Antigo</h3>", unsafe_allow_html=True)
            if os.path.exists(ARQUIVO_CSV):
                df_b = pd.read_csv(ARQUIVO_CSV, dtype={'Prontuário': str})
                lista = [""] + [f"{r['Prontuário']} - {r['Paciente']}" for _, r in df_b.drop_duplicates(subset=['Prontuário']).iterrows()]
                sel = st.selectbox("Selecione o paciente:", lista)
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("Abrir Prontuário Selecionado", use_container_width=True) and sel:
                    id_p = sel.split(" - ")[0]
                    dados = df_b[df_b['Prontuário'] == id_p].iloc[0]
                    st.session_state.paciente_ativo = {"prontuario": id_p, "nome": dados['Paciente'], "mae": dados['Mãe']}
                    st.rerun()
            else: st.info("Sem registros no momento.")
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
        
        tabs = st.tabs(["📊 Painel Visual", "👁️ Visão", "🔄 Cushing", "💧 Fístula", "🚰 D.I.", "🧂 Sódio", "🦠 Meningite", "📈 Recidiva (Gigantes)", "🧬 Acromegalia", "📄 Relatório A4"])

        painel_placeholder = tabs[0].empty()
        relatorio_placeholder = tabs[9].empty()

        with tabs[1]: 
            st.markdown("<div class='calc-info'><b>O que calcula:</b> Estima a probabilidade de melhora visual ou recuperação do campo visual do paciente após a descompressão cirúrgica.</div>", unsafe_allow_html=True)
            st.markdown("<div class='input-card'><h4>👁️ Recuperação Visual</h4>", unsafe_allow_html=True)
            v1, v2 = st.columns(2)
            with v1: 
                v_q = st.toggle("Havia compressão do quiasma óptico?", help="Avaliado por ressonância magnética (RM) coronal. A compressão direta piora o basal, mas tem grande potencial de descompressão.")
                v_d = st.toggle("Apresentava defeito campimétrico difuso?", help="Depressão generalizada da sensibilidade em toda a campimetria visual computadorizada.")
            with v2: 
                v_m = st.number_input("Duração dos sintomas visuais (meses):", 0, help="Tempo total em meses desde que o paciente notou a primeira alteração na visão.")
                v_md = st.number_input("Mean Defect (MD) pré-operatório (dB):", 0.0, help="Valor do 'Mean Defect' (em módulo) extraído do exame de campo visual computadorizado.")
            
            if st.button("Calcular e Salvar Probabilidade Visual", key="btn_visao"):
                res = risco_melhora_visual_ji_2023(v_q, v_d, v_m, v_md)
                params = f"Compressão Quiasma: {'Sim' if v_q else 'Não'} | Defeito Difuso: {'Sim' if v_d else 'Não'} | Sintomas: {v_m} meses | MD: {v_md} dB"
                st.session_state.visao_res = res
                salvar_registro("Prognóstico Visual", res, "melhora", params)
            
            if st.session_state.visao_res is not None:
                st.success("Cálculo realizado e salvo com sucesso! Você pode visualizar o histórico no Painel Visual.")
                st.metric("Probabilidade Calculada", f"{st.session_state.visao_res:.1f}%")
                
            with st.expander("📚 Referência Científica"):
                st.markdown("""
                **Ji X, Zhuang X, Yang S, et al.** Visual field improvement after endoscopic transsphenoidal surgery in patients with pituitary adenoma. *Front Oncol*. 2023;13:1108883.  
                **DOI:** [10.3389/fonc.2023.1108883](https://doi.org/10.3389/fonc.2023.1108883)
                """)
            st.markdown("</div>", unsafe_allow_html=True)
    
        with tabs[2]: 
            st.markdown("<div class='calc-info'><b>O que calcula:</b> Utiliza o Modelo CuPeR para prever o risco de persistência ou recorrência da Doença de Cushing a longo prazo.</div>", unsafe_allow_html=True)
            st.markdown("<div class='input-card'><h4>🔄 Doença de Cushing</h4>", unsafe_allow_html=True)
            
            help_hardy = """
            **Classificação Radiológica de Hardy (Grau de Invasão):**
            * **Grau 0:** Sela túrcica intacta e de aspecto normal.
            * **Grau 1:** Microadenoma (<10 mm); sela intacta, podendo ter assimetria óssea focal.
            * **Grau 2:** Macroadenoma (≥10 mm); sela alargada globalmente, mas com o assoalho intacto.
            * **Grau 3:** Tumor invasivo; erosão óssea localizada ou destruição parcial.
            * **Grau 4:** Destruição difusa e extensa da base do crânio.
            """
            
            c1, c2 = st.columns(2)
            with c1: 
                c_dur = st.number_input("Duração dos sintomas antes da cirurgia (meses):", 0, key="c1", help="Tempo de exposição clínica documentada aos sinais/sintomas do hipercortisolismo.")
                c_cp = st.toggle("O paciente possui cirurgia pituitária prévia?", help="Se a cirurgia atual for uma reabordagem, o risco de falha aumenta significativamente.")
            with c2: 
                c_h = st.select_slider("Classificação de Invasão de Hardy:", [0,1,2,3,4], value=2, help=help_hardy)
                c_l = st.selectbox("Localização predominante do Tumor na RM:", ["Bilateral","Direita","Esquerda","Central","Haste"], help="Baseado na interpretação da Ressonância Dinâmica da Sela Túrcica.")
            
            if st.button("Calcular e Salvar Risco de Recorrência", key="btn_cushing"):
                res = risco_recorrencia_cushing_cuper_2025(c_dur, c_h, c_l, c_cp)
                params = f"Sintomas: {c_dur} meses | Cirurgia Prévia: {'Sim' if c_cp else 'Não'} | Grau Hardy: {c_h} | Localização: {c_l}"
                st.session_state.cushing_res = res
                salvar_registro("Recorrência Cushing", res, "risco", params)
            
            if st.session_state.cushing_res is not None:
                st.success("Cálculo realizado e salvo com sucesso!")
                st.metric("Risco Calculado", f"{st.session_state.cushing_res:.1f}%")
                
            with st.expander("📚 Referência Científica"):
                st.markdown("""
                **Sharifi G, Paraandavaji E, Akbari Dilmaghani N, et al.** The CuPeR model: A dynamic online tool for predicting Cushing's disease persistence and recurrence after pituitary surgery. *J Clin Transl Endocrinol*. 2025;41:100417.  
                **DOI:** [10.1016/j.jcte.2025.100417](https://doi.org/10.1016/j.jcte.2025.100417)
                """)
            st.markdown("</div>", unsafe_allow_html=True)

        with tabs[3]: 
            st.markdown("<div class='calc-info'><b>O que calcula:</b> Avalia o risco de fístula liquórica (vazamento de LCR) durante o período pós-operatório imediato e mediato.</div>", unsafe_allow_html=True)
            st.markdown("<div class='input-card'><h4>💧 Fístula de Líquor</h4>", unsafe_allow_html=True)
            
            help_kelly = """
            **Grau de Kelly (Vazamento Intraoperatório de LCR):**
            * **Grau 0:** Nenhuma fístula liquórica observada.
            * **Grau 1:** Fístula pequena (gotejamento/transudação) sem um defeito dural óbvio.
            * **Grau 2:** Fístula moderada com fluxo claro através de um defeito definitivo.
            * **Grau 3:** Fístula de alto fluxo (grande defeito dural, exposição do 3º ventrículo).
            """
            
            f1, f2 = st.columns(2)
            with f1: 
                f_k = st.toggle("Grau de Kelly intraoperatório ≥ 2?", help=help_kelly)
                f_s = st.toggle("Extensão suprasselar do tumor ≥ Grau B?", help="Extensão do tumor para as cisternas suprasselares, deslocando ou elevando o quiasma óptico.")
            with f2: 
                f_p = st.toggle("Pneumoencéfalo pós-operatório ≥ Grau 3 na TC?", help="Grau 3 significa volume de ar intracraniano considerável indicando comunicação ampla do espaço subaracnoideo.")
                f_j = st.number_input("Tamanho estimado da janela óssea selar (mm):", 0.0, help="Diâmetro da craniectomia/abertura do assoalho selar (osso esfenoidal) realizada pelo cirurgião.")
            
            if st.button("Calcular e Salvar Risco de Fístula", key="btn_fistula"):
                res = risco_fistula_lcr_zhang_2025(f_k, f_s, f_p, f_j)
                params = f"Kelly ≥ 2: {'Sim' if f_k else 'Não'} | Supra ≥ B: {'Sim' if f_s else 'Não'} | Pneumoencéfalo ≥ 3: {'Sim' if f_p else 'Não'} | Janela óssea: {f_j} mm"
                st.session_state.fistula_res = res
                salvar_registro("Risco Fístula LCR", res, "risco", params)

            if st.session_state.fistula_res is not None:
                st.success("Cálculo realizado e salvo com sucesso!")
                st.metric("Risco Calculado", f"{st.session_state.fistula_res:.1f}%")
                
            with st.expander("📚 Referência Científica"):
                st.markdown("""
                **Zhang J, He Y, Ning Y, et al.** Risk factors and predictive model for postoperative cerebrospinal fluid leakage following endoscopic endonasal pituitary adenoma surgery. *Front Endocrinol*. 2025;16:1695573.  
                **DOI:** [10.3389/fendo.2025.1695573](https://doi.org/10.3389/fendo.2025.1695573)
                """)
            st.markdown("</div>", unsafe_allow_html=True)

        with tabs[4]: 
            st.markdown("<div class='calc-info'><b>O que calcula:</b> Prediz a probabilidade de desenvolver Diabetes Insipidus central no pós-operatório devido à manipulação da neuro-hipófise.</div>", unsafe_allow_html=True)
            st.markdown("<div class='input-card'><h4>🚰 Diabetes Insipidus</h4>", unsafe_allow_html=True)
            d1, d2 = st.columns(2)
            with d1: 
                di_d = st.checkbox("O paciente possui Diabetes Mellitus prévio?")
                di_h = st.checkbox("O paciente possui Hipertensão Arterial Sistêmica?")
                di_ca = st.checkbox("O paciente possui Cardiopatia prévia?")
            with d2: 
                di_co = st.number_input("Nível de Cortisol basal pré-operatório (mmol/L):", 0.0, help="Nível de cortisol sérico obtido preferencialmente às 8h da manhã.")
                di_f = st.toggle("Apresentou fístula liquórica documentada no pós-operatório?")
                di_r = st.toggle("A textura do tumor era firme/rígida na avaliação intraoperatória?", help="Tumores duros exigem maior tração e curetagem, aumentando o risco mecânico adjacente à haste hipofisária.")
            
            if st.button("Calcular e Salvar Risco de D.I.", key="btn_di"):
                res = risco_diabetes_insipidus_li_2024(di_d, di_h, di_ca, di_co, di_f, di_r)
                params = f"DM: {'Sim' if di_d else 'Não'} | HAS: {'Sim' if di_h else 'Não'} | Cardiopatia: {'Sim' if di_ca else 'Não'} | Cortisol pré-op: {di_co} | Fístula: {'Sim' if di_f else 'Não'} | Tumor Rígido: {'Sim' if di_r else 'Não'}"
                st.session_state.di_res = res
                salvar_registro("Diabetes Insipidus", res, "risco", params)
                
            if st.session_state.di_res is not None:
                st.success("Cálculo realizado e salvo com sucesso!")
                st.metric("Risco Calculado", f"{st.session_state.di_res:.1f}%")
                
            with st.expander("📚 Referência Científica"):
                st.markdown("""
                **Li XJ, Peng Z, Wang YF, et al.** Analysis of factors influencing the occurrence of diabetes insipidus following neuroendoscopic transsphenoidal resection of pituitary adenomas and risk assessment. *Heliyon*. 2024;10(1):e38694.  
                **DOI:** [10.1016/j.heliyon.2024.e38694](https://doi.org/10.1016/j.heliyon.2024.e38694)
                """)
            st.markdown("</div>", unsafe_allow_html=True)

        with tabs[5]: 
            st.markdown("<div class='calc-info'><b>O que calcula:</b> Risco de Hiponatremia Tardia (Delayed Postoperative Hyponatremia - DPH), usualmente ocorrendo entre o 4º e o 7º dia pós-operatório (fase secundária de SIADH).</div>", unsafe_allow_html=True)
            st.markdown("<div class='input-card'><h4>🧂 Hiponatremia Tardia (DPH)</h4>", unsafe_allow_html=True)
            mod_h = st.radio("Selecione a base do modelo preditivo:", ["Modelo de Sangue (Cai et al.)", "Modelo de Imagem/Hormonal (Tan et al.)"])
            hp12 = st.toggle("Houve queda do Sódio sérico nos Dias 1 e 2 pós-op?", help="Sódio em declínio na fase aguda é um preditor clínico muito forte do desenvolvimento de SIADH tardia.")
            
            if mod_h == "Modelo de Sangue (Cai et al.)":
                mo = st.number_input("Porcentagem de Monócitos no hemograma (%):", 0.0, help="O valor de monócitos relativos obtidos no hemograma de rotina pós-operatório.")
                pt = st.number_input("Tempo de Protrombina (segundos):", 0.0, help="Tempo de coagulação em segundos (PT/TAP).")
                if st.button("Calcular e Salvar Risco (Modelo Cai)", key="btn_hipo_cai"):
                    res = risco_pdh_cai_2023(hp12, mo, pt)
                    params = f"Queda Sódio D1-D2: {'Sim' if hp12 else 'Não'} | Monócitos: {mo}% | Tempo de Protrombina: {pt} seg"
                    st.session_state.hipo_res = res
                    salvar_registro("DPH (Modelo Cai)", res, "risco", params)
            else:
                pr = st.number_input("Nível de Prolactina basal pré-op (ng/mL):", 0.0, help="Nível sérico medido no sangue antes da cirurgia.")
                dia = st.number_input("Elevação estimada do Diafragma Selar (mm):", 0.0, help="Elevação do diafragma selar acima da linha basilar na RM sagital/coronal.")
                if st.button("Calcular e Salvar Risco (Modelo Tan)", key="btn_hipo_tan"):
                    res = risco_pdh_tan_2025(pr, dia, hp12)
                    params = f"Queda Sódio D1-D2: {'Sim' if hp12 else 'Não'} | Prolactina pré-op: {pr} ng/mL | Elevação Diafragma: {dia} mm"
                    st.session_state.hipo_res = res
                    salvar_registro("DPH (Modelo Tan)", res, "risco", params)
                    
            if st.session_state.hipo_res is not None:
                st.success("Cálculo realizado e salvo com sucesso!")
                st.metric("Risco Calculado", f"{st.session_state.hipo_res:.1f}%")
                
            with st.expander("📚 Referências Científicas"):
                st.markdown("""
                **Cai X, et al.** Predictors and dynamic online nomogram for postoperative delayed hyponatremia after endoscopic transsphenoidal surgery for pituitary adenomas. *Chin Neurosurg J*. 2023;9(1):19.  
                **DOI:** [10.1186/s41016-023-00334-3](https://doi.org/10.1186/s41016-023-00334-3)
                
                **Tan H, et al.** Predictive model of delayed hyponatremia after endoscopic endonasal transsphenoidal resection of pituitary adenoma. *Front Hum Neurosci*. 2025;19:1674519.  
                **DOI:** [10.3389/fnhum.2025.1674519](https://doi.org/10.3389/fnhum.2025.1674519)
                """)
            st.markdown("</div>", unsafe_allow_html=True)

        with tabs[6]: 
            st.markdown("<div class='calc-info'><b>O que calcula:</b> Estima o risco de meningite bacteriana pós-operatória baseado em dados anatômicos e variáveis cirúrgicas.</div>", unsafe_allow_html=True)
            st.markdown("<div class='input-card'><h4>🦠 Meningite Pós-operatória</h4>", unsafe_allow_html=True)
            m1, m2 = st.columns(2)
            with m1: 
                md = st.number_input("Duração total da Cirurgia (horas):", 0.0, help="Tempo cirúrgico prolongado aumenta exponencialmente o risco de contaminação cruzada e meningite (OR 2.68).")
                mf = st.toggle("Houve fístula de LCR identificada intraoperatória?", help="Vazamento de líquor durante a cirurgia é o principal preditor independente (aumenta o risco em ~9 vezes).")
            with m2: 
                mt = st.number_input("Diâmetro máximo do Tumor na RM (cm):", 0.0, help="A cada 1 cm adicional no tamanho do tumor o risco aumenta em 2.7x, devido à maior complexidade de ressecção e área de exposição.")
            
            if st.button("Calcular e Salvar Risco de Meningite", key="btn_meningite"):
                res = risco_meningite_zhou_2025(md, mt, mf)
                params = f"Duração Cirurgia: {md} horas | Diâmetro do Tumor: {mt} cm | Fístula Intraoperatória: {'Sim' if mf else 'Não'}"
                st.session_state.meningite_res = res
                salvar_registro("Risco Meningite", res, "risco", params)
                
            if st.session_state.meningite_res is not None:
                st.success("Cálculo realizado e salvo com sucesso!")
                st.metric("Risco Calculado", f"{st.session_state.meningite_res:.1f}%")
                
            with st.expander("📚 Referência Científica"):
                st.markdown("""
                **Zhou P, Shi J, Long Z, et al.** Predictive model for meningitis after pituitary tumor resection by endoscopic nasal trans-sphenoidal sinus approach. *Eur J Med Res*. 2025;30:738.  
                **DOI:** [10.1186/s40001-025-03016-1](https://doi.org/10.1186/s40001-025-03016-1)
                """)
            st.markdown("</div>", unsafe_allow_html=True)
            
        with tabs[7]: 
            st.markdown("<div class='calc-info'><b>O que calcula:</b> Estima o risco de <b>recorrência ou progressão num horizonte de 5 anos</b> especificamente para macroadenomas e adenomas gigantes (diâmetros superiores a 3-4 cm).</div>", unsafe_allow_html=True)
            st.markdown("<div class='input-card'><h4>📈 Recidiva (Gigantes)</h4>", unsafe_allow_html=True)
            
            help_knosp = """
            **Classificação de Knosp (Invasão do Seio Cavernoso):**
            * **Graus 0-1:** Tumor não ultrapassa o centro da artéria carótida interna.
            * **Graus 2-3:** Tumor ultrapassa o centro da artéria ou invade a parede lateral do seio cavernoso.
            * **Grau 4:** Envolvimento completo (encasement) da artéria carótida interna intracavernosa.
            """
            
            help_res = """
            **Grau de Ressecção Cirúrgica Final:**
            * **GTR:** Ressecção Total (>95%)
            * **NTR:** Ressecção Quase Total (90-95%)
            * **STR:** Ressecção Subtotal (70-90%)
            * **PR:** Ressecção Parcial (<70%)
            """
            
            ch1, ch2 = st.columns(2)
            with ch1:
                chen_res_op = st.selectbox("Extensão estimada da Ressecção Cirúrgica:", ["Ressecção Total (GTR > 95%)", "Ressecção Quase Total (NTR 90-95%)", "Ressecção Subtotal (STR 70-90%)", "Ressecção Parcial (PR < 70%)"], help=help_res)
                chen_knosp = st.selectbox("Classificação de Knosp (RM Pré-op):", ["Graus 0 - 1", "Graus 2 - 3", "Grau 4"], help=help_knosp)
                chen_tabagismo = st.toggle("O paciente possui histórico de tabagismo?")
            with ch2:
                chen_ki67 = st.toggle("Índice de proliferação tumoral Ki-67 ≥ 3%?", help="Marcador imuno-histoquímico de proliferação celular (geralmente avaliado após a biópsia/cirurgia).")
                chen_bmi = st.toggle("Índice de Massa Corporal (IMC) ≥ 25 kg/m²?", help="Identifica pacientes com sobrepeso ou obesidade, o que se demonstrou ser um fator de risco associado à recidiva.")
                
            if st.button("Calcular e Salvar Risco de Recidiva (5 Anos)", key="btn_chen"):
                res = risco_progressao_chen_2021(chen_res_op, chen_knosp, chen_ki67, chen_bmi, chen_tabagismo)
                params = f"Ressecção: {chen_res_op} | Knosp: {chen_knosp} | Ki-67 ≥3%: {'Sim' if chen_ki67 else 'Não'} | IMC ≥25: {'Sim' if chen_bmi else 'Não'} | Tabagismo: {'Sim' if chen_tabagismo else 'Não'}"
                st.session_state.chen_res = res
                salvar_registro("Risco de Recidiva 5 Anos", res, "risco", params)
                
            if st.session_state.chen_res is not None:
                st.success("Cálculo realizado e salvo com sucesso!")
                st.metric("Risco Calculado de Progressão (5 Anos)", f"{st.session_state.chen_res:.1f}%")
                
            with st.expander("📚 Referência Científica"):
                st.markdown("""
                **Chen Y, Cai F, Cao J, et al.** Analysis of Related Factors of Tumor Recurrence or Progression After Transnasal Sphenoidal Surgical Treatment of Large and Giant Pituitary Adenomas and Establish a Nomogram to Predict Tumor Prognosis. *Front Endocrinol*. 2021;12:793337.  
                **DOI:** [10.3389/fendo.2021.793337](https://doi.org/10.3389/fendo.2021.793337)
                """)
            st.markdown("</div>", unsafe_allow_html=True)
            
        with tabs[8]: 
            st.markdown("<div class='calc-info'><b>O que calcula:</b> Probabilidade de <b>Remissão Bioquímica a longo prazo</b> em pacientes com Acromegalia (adenomas secretores de GH), definindo a necessidade de vigilância ou terapias adjuvantes.</div>", unsafe_allow_html=True)
            st.markdown("<div class='input-card'><h4>🧬 Acromegalia (Remissão Bioquímica)</h4>", unsafe_allow_html=True)
            
            help_knosp_acro = """
            **Classificação de Knosp (Invasão do Seio Cavernoso):**
            * **Graus 0, 1 e 2:** Tumor não atinge ou não ultrapassa significativamente a linha tangente lateral da artéria carótida interna.
            * **Graus 3A, 3B e 4:** Tumor ultrapassa a tangente lateral da carótida (compartimentos superior/inferior) ou envolve completamente a artéria. É um preditor negativo de remissão.
            """
            
            ac1, ac2 = st.columns(2)
            with ac1:
                acro_idade = st.number_input("Idade do paciente no diagnóstico (anos):", 0, help="Idades mais jovens (≤ 50 anos) geralmente estão associadas a um comportamento tumoral mais agressivo e menores taxas de remissão na acromegalia.")
                acro_diam = st.number_input("Diâmetro máximo do tumor na RM (cm):", 0.0, step=0.1, help="Tumores macroadenomas ≥ 1.5 cm apresentam um risco significativamente maior de doença persistente.")
                acro_knosp = st.selectbox("Classificação de Invasão de Knosp:", ["Grau 0", "Grau 1", "Grau 2", "Grau 3A", "Grau 3B", "Grau 4"], help=help_knosp_acro)
            with ac2:
                acro_igf1 = st.number_input("Índice de IGF-1 basal pré-operatório:", 0.0, step=0.1, help="Valor do paciente dividido pelo limite superior do normal para a sua idade/sexo. Um índice ≥ 3.0 afeta negativamente a remissão.")
                acro_gh = st.number_input("Nível de GH basal no diagnóstico (ng/mL):", 0.0, step=0.1, help="Níveis de GH ≥ 8.0 ng/mL no diagnóstico indicam forte atividade secretória e menor probabilidade de cura isolada por cirurgia.")
                
            if st.button("Calcular e Salvar Probabilidade de Remissão", key="btn_acro"):
                res = remissao_acromegalia_cohen_2024(acro_idade, acro_diam, acro_knosp, acro_igf1, acro_gh)
                params = f"Idade: {acro_idade} anos | Diâmetro: {acro_diam} cm | Knosp: {acro_knosp} | Índice IGF-1: {acro_igf1} | GH basal: {acro_gh} ng/mL"
                st.session_state.acro_res = res
                salvar_registro("Remissão Bioquímica (Acromegalia)", res, "melhora", params)
                
            if st.session_state.acro_res is not None:
                if st.session_state.acro_res >= 60:
                    st.success("Cálculo realizado e salvo com sucesso! Alta probabilidade de remissão.")
                elif st.session_state.acro_res >= 30:
                    st.warning("Cálculo realizado. Probabilidade moderada de remissão.")
                else:
                    st.error("Cálculo realizado. Risco elevado de doença persistente (baixa probabilidade de remissão).")
                st.metric("Chance de Remissão Calculada", f"{st.session_state.acro_res:.1f}%")
                
            with st.expander("📚 Referência Científica"):
                st.markdown("""
                **Cohen-Cohen S, Rindler R, Botello Hernandez E, et al.** A Novel Preoperative Score to Predict Long-Term Biochemical Remission in Patients with Growth-Hormone Secreting Pituitary Adenomas. *World Neurosurg*. 2024;182:e882-e890.  
                **DOI:** [10.1016/j.wneu.2023.12.076](https://doi.org/10.1016/j.wneu.2023.12.076)
                """)
            st.markdown("</div>", unsafe_allow_html=True)

        # =======================================================
        # PREENCHIMENTO DOS PLACEHOLDERS (ATUALIZAÇÃO DINÂMICA)
        # =======================================================
        with painel_placeholder.container():
            st.subheader("📊 Resultados Consolidados e Arquivados")
            if os.path.exists(ARQUIVO_CSV):
                df_h = pd.read_csv(ARQUIVO_CSV, dtype={'Prontuário': str})
                df_p = df_h[df_h['Prontuário'] == str(st.session_state.paciente_ativo['prontuario'])]
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
            st.info("Clique no botão abaixo para imprimir ou salvar como PDF nativo do sistema. Nas configurações de impressão, ative **'Gráficos de segundo plano / Background graphics'** para manter as cores do cabeçalho.")
            
            linhas_html = ""
            if os.path.exists(ARQUIVO_CSV):
                df_rel = pd.read_csv(ARQUIVO_CSV, dtype={'Prontuário': str})
                df_rel_pac = df_rel[df_rel['Prontuário'] == str(st.session_state.paciente_ativo['prontuario'])]
                
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
                @media print {{
                    body {{ background: white; padding: 0; display: block; }}
                    .no-print {{ display: none !important; }}
                    .a4-page {{ width: 100%; height: auto; padding: 0; box-shadow: none; border: none; margin: 0; }}
                }}
            </style>
            </head>
            <body>
                <div style="width: 210mm; max-width: 100%;">
                    <div class="no-print">
                        <button class="print-button" onclick="window.print()">🖨️ CLIQUE AQUI PARA IMPRIMIR OU SALVAR EM PDF</button>
                    </div>
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
                        
                        <div style="font-size: 11px; color: #666; text-align: justify; background: #fff3cd; padding: 15px; border-radius: 5px; border-left: 3px solid #ffc107;">
                            <b style="color: #856404;">Aviso Clínico:</b> Este documento reflete as estimativas de probabilidade baseadas nos dados inseridos e em modelos preditivos validados na literatura científica. Estes resultados destinam-se a apoiar a tomada de decisão médica e não substituem o julgamento clínico individualizado.
                        </div>
                        
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
# HISTÓRICO GERAL
# ==========================================
elif nav == "⚙️ Histórico Geral":
    st.title("⚙️ Gerenciamento de Dados Clínicos")
    if os.path.exists(ARQUIVO_CSV):
        df_g = pd.read_csv(ARQUIVO_CSV, dtype={'Prontuário': str})
        st.dataframe(df_g.sort_values(by="Data/Hora", ascending=False), use_container_width=True, hide_index=True)
        st.download_button("📥 Exportar Planilha Completa (CSV)", df_g.to_csv(index=False).encode('utf-8'), "historico_neuro.csv", "text/csv")
        st.markdown("---")
        st.subheader("🗑️ Excluir Registro do Sistema")
        lista_d = [""] + [f"{r['Prontuário']} - {r['Paciente']}" for _, r in df_g.drop_duplicates(subset=['Prontuário']).iterrows()]
        del_sel = st.selectbox("Selecione o paciente para apagar permanentemente:", lista_d)
        if st.button("🚨 CONFIRMAR EXCLUSÃO") and del_sel:
            id_d = del_sel.split(" - ")[0]
            df_g[df_g['Prontuário'] != id_d].to_csv(ARQUIVO_CSV, index=False, encoding='utf-8')
            st.success("Registro removido com sucesso."); st.rerun()
    else: st.info("Nenhum dado registrado.")

# Marca d'água invisível que não quebra o layout
st.markdown("<div class='watermark'>Made By Vinícius Bacelar Ferreira</div>", unsafe_allow_html=True)
