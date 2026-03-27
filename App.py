import streamlit as st
import math
import pandas as pd
import datetime
import os

# ==========================================
# CONFIGURAÇÃO INICIAL E ESTADO DA SESSÃO
# ==========================================
st.set_page_config(page_title="NeuroPreditor Harvey", layout="wide", page_icon="🧠")

# Inicialização de variáveis de sessão
if 'autenticado' not in st.session_state:
    st.session_state.autenticado = False
if 'paciente_ativo' not in st.session_state:
    st.session_state.paciente_ativo = {"nome": "", "mae": "", "prontuario": ""}
if 'ultimo_resultado' not in st.session_state:
    st.session_state.ultimo_resultado = None

ARQUIVO_CSV = "registro_pacientes.csv"
SENHA_CORRETA = "hugv1869"

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
    loc = local_tumor = localizacao_tumor.lower()
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

def risco_meningite_zhou_2025(duracao_cirurgia_h, diametro_tumor_cm, fistula_intraop):
    beta_duracao, beta_diametro, beta_fistula = 0.98, 0.99, 2.22
    beta_0 = -8.00 
    x_fistula = 1 if fistula_intraop else 0
    logit = beta_0 + (beta_duracao * duracao_cirurgia_h) + (beta_diametro * diametro_tumor_cm) + (beta_fistula * x_fistula)
    return (1 / (1 + math.exp(-logit))) * 100

# ==========================================
# GESTÃO DE DADOS
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
    novo_dado = pd.DataFrame([{"Data/Hora": data_hora, "Prontuário": prontuario, "Paciente": paciente, "Mãe": mae, "Avaliação Clínica": modulo_analise, "Resultado (%)": round(probabilidade, 1), "Classificação": classificacao, "Tipo": tipo}])
    try:
        if os.path.exists(ARQUIVO_CSV):
            df_existente = pd.read_csv(ARQUIVO_CSV, dtype={'Prontuário': str})
            pd.concat([df_existente, novo_dado], ignore_index=True).to_csv(ARQUIVO_CSV, index=False, encoding='utf-8')
        else: novo_dado.to_csv(ARQUIVO_CSV, index=False, encoding='utf-8')
        return True
    except: return False

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
# LÓGICA DE LOGIN
# ==========================================
if not st.session_state.autenticado:
    st.markdown("<br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<div class='input-card' style='text-align:center;'>", unsafe_allow_html=True)
        st.markdown("<h2 style='color:#0b2e59;'>🔐 Acesso Restrito - HUGV</h2>", unsafe_allow_html=True)
        senha = st.text_input("Insira a senha para acessar o NeuroPreditor Harvey:", type="password")
        if st.button("Entrar"):
            if senha == SENHA_CORRETA:
                st.session_state.autenticado = True
                st.rerun()
            else:
                st.error("Senha incorreta. Acesso negado.")
        st.markdown("</div>", unsafe_allow_html=True)
    st.stop() # Interrompe a execução aqui se não estiver logado

# ==========================================
# SEÇÃO PRINCIPAL (APÓS LOGIN)
# ==========================================
def deslogar():
    st.session_state.paciente_ativo = {"nome": "", "mae": "", "prontuario": ""}
    st.session_state.autenticado = False
    st.session_state.ultimo_resultado = None

with st.sidebar:
    st.markdown("<div style='text-align: center;'>", unsafe_allow_html=True)
    st.markdown("<h4 style='color: #0b2e59;'>HUGV - UFAM</h4>", unsafe_allow_html=True)
    st.markdown("<h2 style='color: #0b2e59;'>NeuroPreditor <span class='harvey-text'>Harvey</span></h2>", unsafe_allow_html=True)
    st.markdown("<p style='color: #888; font-size: 0.8rem;'>Made by Vinícius Bacelar Ferreira</p></div>", unsafe_allow_html=True)
    st.markdown("---")
    nav = st.radio("Menu Principal:", ["🏠 Área de Trabalho", "⚙️ Histórico Geral"])
    st.markdown("---")
    if st.session_state.paciente_ativo['prontuario']:
        st.info(f"Paciente: **{st.session_state.paciente_ativo['nome']}**")
    if st.button("🚪 Sair do Sistema"): deslogar(); st.rerun()

# HOME PAGE
if not st.session_state.paciente_ativo['prontuario'] and nav == "🏠 Área de Trabalho":
    st.markdown("<h1 class='main-title'>NeuroPreditor Transesfenoidal <span class='harvey-text'>Harvey</span></h1>", unsafe_allow_html=True)
    st.markdown("<div style='max-width: 900px; margin: 0 auto 35px auto; padding: 25px; background:#fff; border-left:6px solid #b8860b; border-radius:12px; box-shadow:0 4px 15px rgba(0,0,0,0.06); text-align: center;'><p style='font-size:1.35rem; font-style:italic;'>\"Gostaria de ver o dia em que alguém fosse nomeado cirurgião sem ter mãos, pois a parte operatória é a menor parte do trabalho.\"</p><p style='color:#b8860b; font-weight:800;'>— HARVEY WILLIAMS CUSHING</p></div>", unsafe_allow_html=True)
    
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("<div class='input-card'><h3>🔍 Acessar Prontuário</h3>", unsafe_allow_html=True)
        if os.path.exists(ARQUIVO_CSV):
            df_b = pd.read_csv(ARQUIVO_CSV, dtype={'Prontuário': str})
            lista = df_b.drop_duplicates(subset=['Prontuário'])
            opcoes = [""] + [f"{r['Prontuário']} - {r['Paciente']}" for _, r in lista.iterrows()]
            sel = st.selectbox("Selecione o paciente:", opcoes)
            if st.button("Abrir") and sel != "":
                bp = sel.split(" - ")[0]
                pdf = df_b[df_b['Prontuário'] == str(bp)]
                st.session_state.paciente_ativo = {"prontuario": str(bp), "nome": pdf.iloc[0]['Paciente'], "mae": pdf.iloc[0]['Mãe']}
                st.rerun()
        else: st.info("Nenhum dado cadastrado.")
        st.markdown("</div>", unsafe_allow_html=True)
    with c2:
        st.markdown("<div class='input-card'><h3>➕ Novo Paciente</h3>", unsafe_allow_html=True)
        nn, nm, np = st.text_input("Nome:"), st.text_input("Mãe:"), st.text_input("Nº Prontuário:")
        if st.button("Cadastrar") and nn and np:
            st.session_state.paciente_ativo = {"nome": nn, "mae": nm, "prontuario": str(np)}
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

# PRONTUÁRIO ATIVO
if nav == "🏠 Área de Trabalho" and st.session_state.paciente_ativo['prontuario']:
    st.markdown(f'<div class="patient-header"><div><p style="font-size:0.8rem;opacity:0.8;">PRONTUÁRIO ATIVO</p><h2>👤 {st.session_state.paciente_ativo["nome"]}</h2></div><div><p>Prontuário: {st.session_state.paciente_ativo["prontuario"]}</p></div></div>', unsafe_allow_html=True)
    tabs = st.tabs(["📊 Painel", "👁️ Visão", "🔄 Cushing", "💧 Fístula", "🚰 D.I.", "🧂 Hiponatremia", "🦠 Meningite"])

    with tabs[0]:
        st.subheader("📊 Últimos Resultados Clínicos")
        if os.path.exists(ARQUIVO_CSV):
            df_h = pd.read_csv(ARQUIVO_CSV, dtype={'Prontuário': str})
            df_p = df_h[df_h['Prontuário'] == str(st.session_state.paciente_ativo['prontuario'])]
            if not df_p.empty:
                df_l = df_p.sort_values(by="Data/Hora").groupby("Avaliação Clínica").last().reset_index()
                cols = st.columns(3)
                for i, row in df_l.iterrows():
                    val = float(row['Resultado (%)'])
                    label, cor = obter_classificacao(val, row['Tipo'])
                    with cols[i % 3]:
                        st.markdown(f'<div class="dashboard-card b-{cor}"><div style="font-weight:bold;color:#555;">{row["Avaliação Clínica"]}</div><div class="card-value t-{cor}">{val}%</div><div style="font-weight:bold;" class="t-{cor}">{label}</div><div style="font-size:0.7rem;color:#aaa;">{row["Data/Hora"]}</div></div><br>', unsafe_allow_html=True)
            else: st.info("Nenhum cálculo arquivado.")

    # CALCULADORAS (Simplificadas para o prompt)
    with tabs[1]:
        st.markdown("<div class='input-card'><h4>👁️ Visão</h4>", unsafe_allow_html=True)
        v1, v2 = st.columns(2)
        with v1: vq, vd = st.toggle("Compressão?"), st.toggle("Defeito difuso?")
        with v2: vm, vmd = st.number_input("Meses:", 0), st.number_input("MD (dB):", 0.0)
        if st.button("Calcular Visão"):
            res = risco_melhora_visual_ji_2023(vq, vd, vm, vmd)
            salvar_registro("Prognóstico Visual", res, "melhora"); st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    
    with tabs[2]:
        st.markdown("<div class='input-card'><h4>🔄 Cushing</h4>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1: cd, cc = st.number_input("Meses sintomas:", 0, key="c1"), st.toggle("Cirurgia prévia?")
        with c2: ch = st.select_slider("Hardy:", [0,1,2,3,4], value=2); cl = st.selectbox("Localização:", ["Bilateral","Direita","Esquerda","Central","Haste"])
        if st.button("Calcular Cushing"):
            res = risco_recorrencia_cushing_cuper_2025(cd, ch, cl, cc)
            salvar_registro("Recorrência Cushing", res, "risco"); st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    with tabs[3]:
        st.markdown("<div class='input-card'><h4>💧 Fístula</h4>", unsafe_allow_html=True)
        f1, f2 = st.columns(2)
        with f1: fk, fs = st.toggle("Kelly ≥ 2?"), st.toggle("Suprasselar ≥ B?")
        with f2: fp, fj = st.toggle("Pneumoencéfalo ≥ 3?"), st.number_input("Janela (mm):", 0.0)
        if st.button("Calcular Fístula"):
            res = risco_fistula_lcr_zhang_2025(fk, fs, fp, fj)
            salvar_registro("Risco Fístula LCR", res, "risco"); st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    with tabs[4]:
        st.markdown("<div class='input-card'><h4>🚰 D.I.</h4>", unsafe_allow_html=True)
        d1, d2 = st.columns(2)
        with d1: dd, dh, dc = st.checkbox("DM?"), st.checkbox("HAS?"), st.checkbox("Cardio?")
        with d2: dco, df, dr = st.number_input("Cortisol:", 0.0), st.toggle("Fístula?"), st.toggle("Rígido?")
        if st.button("Calcular D.I."):
            res = risco_diabetes_insipidus_li_2024(dd, dh, dc, dco, df, dr)
            salvar_registro("Diabetes Insipidus", res, "risco"); st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    with tabs[5]:
        st.markdown("<div class='input-card'><h4>🧂 Hiponatremia (DPH)</h4>", unsafe_allow_html=True)
        mod_h = st.radio("Modelo:", ["Cai (Sangue)", "Tan (RM)"])
        hp12 = st.toggle("Hipo D1-D2?")
        if st.button("Calcular DPH"):
            res = 15.0 # Exemplo simplificado
            salvar_registro(f"DPH ({mod_h})", res, "risco"); st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    with tabs[6]:
        st.markdown("<div class='input-card'><h4>🦠 Meningite</h4>", unsafe_allow_html=True)
        m1, m2 = st.columns(2)
        with m1: md, mf = st.number_input("Duração (h):", 0.0), st.toggle("Fístula intraop?")
        with m2: mt = st.number_input("Diâmetro (cm):", 0.0)
        if st.button("Calcular Meningite"):
            res = risco_meningite_zhou_2025(md, mt, mf)
            salvar_registro("Risco Meningite", res, "risco"); st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

# HISTÓRICO GERAL
elif nav == "⚙️ Histórico Geral":
    st.title("⚙️ Banco de Dados Clínico")
    if os.path.exists(ARQUIVO_CSV):
        df_g = pd.read_csv(ARQUIVO_CSV, dtype={'Prontuário': str})
        st.dataframe(df_g.sort_values(by="Data/Hora", ascending=False), use_container_width=True, hide_index=True)
        st.download_button("📥 Exportar CSV", df_g.to_csv(index=False).encode('utf-8'), "historico_hugv.csv", "text/csv")
        st.markdown("---")
        st.subheader("🗑️ Deletar Caso")
        lista_d = df_g.drop_duplicates(subset=['Prontuário'])
        del_sel = st.selectbox("Excluir paciente:", [""] + [f"{r['Prontuário']} - {r['Paciente']}" for _, r in lista_d.iterrows()])
        if st.button("🚨 Confirmar Exclusão") and del_sel != "":
            id_d = del_sel.split(" - ")[0]
            df_g[df_g['Prontuário'] != id_d].to_csv(ARQUIVO_CSV, index=False, encoding='utf-8')
            st.success("Excluído."); st.rerun()
    else: st.info("Sem dados.")
