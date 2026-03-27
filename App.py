import streamlit as st
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
if 'ultimo_resultado' not in st.session_state:
    st.session_state.ultimo_resultado = None

ARQUIVO_CSV = "registro_pacientes.csv"
SENHA_CORRETA = "hugv1869"

# ==========================================
# FUNÇÕES DE CÁLCULO (BACK-END)
# ==========================================

def risco_meningite_zhou_2025(duracao_h, diametro_cm, fistula_intra):
    # Coeficientes do artigo: Operação (0.98), Diâmetro (0.99), Fístula (2.22) [cite: 175]
    beta_duracao, beta_diametro, beta_fistula = 0.98, 0.99, 2.22
    beta_0 = -7.50 # Intercepto estimado
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
    return ("Baixo Risco", "green") if prob < 10 else ("Risco Moderado", "orange") if prob < 25 else ("Alto Risco", "red")

def salvar_registro(mod, prob, tipo):
    pac, mae, pront = st.session_state.paciente_ativo['nome'], st.session_state.paciente_ativo['mae'], str(st.session_state.paciente_ativo['prontuario'])
    classif, _ = obter_classificacao(prob, tipo)
    data = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    novo = pd.DataFrame([{"Data/Hora": data, "Prontuário": pront, "Paciente": pac, "Mãe": mae, "Avaliação Clínica": mod, "Resultado (%)": round(prob, 1), "Classificação": classif, "Tipo": tipo}])
    if os.path.exists(ARQUIVO_CSV):
        df_e = pd.read_csv(ARQUIVO_CSV, dtype={'Prontuário': str})
        pd.concat([df_e, novo], ignore_index=True).to_csv(ARQUIVO_CSV, index=False, encoding='utf-8')
    else: novo.to_csv(ARQUIVO_CSV, index=False, encoding='utf-8')
    return True

# ==========================================
# ESTILOS CSS
# ==========================================
st.markdown("""
<style>
    .stApp { background: linear-gradient(135deg, #021d33 0%, #0b2e59 50%, #1565c0 100%); }
    .login-box { background: rgba(255, 255, 255, 0.08); backdrop-filter: blur(15px); border-radius: 20px; border: 1px solid rgba(255, 255, 255, 0.2); padding: 40px; box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3); text-align: center; max-width: 500px; margin: auto; }
    .watermark { position: fixed; bottom: 20px; right: 30px; opacity: 0.4; color: white; font-family: 'Georgia', serif; font-style: italic; font-size: 0.9rem; pointer-events: none; }
    .main-title { background: -webkit-linear-gradient(45deg, #ffd700, #b8860b); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-weight: 900; font-size: 3.5rem; text-align: center; }
    .patient-header { background: rgba(255, 255, 255, 0.1); border: 1px solid rgba(255,255,255,0.2); backdrop-filter: blur(10px); color: white; padding: 20px; border-radius: 15px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center;}
    .dashboard-card { background: white; border-radius: 15px; padding: 20px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); text-align: center; border-top: 6px solid #ddd; color: #333; }
    .card-value { font-size: 2.8rem; font-weight: 800; margin: 5px 0; }
    .b-green { border-top-color: #2e7d32 !important; } .t-green { color: #2e7d32 !important; }
    .b-orange { border-top-color: #ef6c00 !important; } .t-orange { color: #ef6c00 !important; }
    .b-red { border-top-color: #c62828 !important; } .t-red { color: #c62828 !important; }
    .input-card { background: white; padding: 30px; border-radius: 15px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); margin-top: 20px; color: #333; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# TELA DE LOGIN
# ==========================================
if not st.session_state.autenticado:
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    st.markdown("<div class='login-box'>", unsafe_allow_html=True)
    st.markdown("<h1 style='color: white;'>NeuroPreditor <span style='font-family: Georgia; font-style: italic; color: #ffd700;'>Harvey</span></h1>", unsafe_allow_html=True)
    st.markdown("<p style='color: rgba(255,255,255,0.7);'>Acesso Restrito - Hospital Universitário Getúlio Vargas</p>", unsafe_allow_html=True)
    senha = st.text_input("Senha Institucional:", type="password")
    if st.button("DESBLOQUEAR ACESSO"):
        if senha == SENHA_CORRETA:
            st.session_state.autenticado = True
            st.rerun()
        else: st.error("Senha incorreta.")
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("<div class='watermark'>By Vinícius Bacelar Ferreira</div>", unsafe_allow_html=True)
    st.stop()

# ==========================================
# NAVEGAÇÃO
# ==========================================
with st.sidebar:
    st.markdown("<h2 style='color: #ffd700;'>Harvey</h2>", unsafe_allow_html=True)
    nav = st.radio("Navegação:", ["🏠 Área de Trabalho", "⚙️ Histórico Geral"])
    if st.button("🚪 Sair do Sistema"):
        st.session_state.autenticado = False
        st.rerun()

# --- ÁREA DE TRABALHO ---
if nav == "🏠 Área de Trabalho":
    if not st.session_state.paciente_ativo['prontuario']:
        st.markdown("<h1 class='main-title'>NeuroPreditor Harvey</h1>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("<div class='input-card'><h3>🔍 Acessar Prontuário</h3>", unsafe_allow_html=True)
            if os.path.exists(ARQUIVO_CSV):
                df_b = pd.read_csv(ARQUIVO_CSV, dtype={'Prontuário': str})
                lista = [""] + [f"{r['Prontuário']} - {r['Paciente']}" for _, r in df_b.drop_duplicates(subset=['Prontuário']).iterrows()]
                sel = st.selectbox("Selecione o paciente:", lista)
                if st.button("Abrir") and sel:
                    id_p = sel.split(" - ")[0]
                    dados = df_b[df_b['Prontuário'] == id_p].iloc[0]
                    st.session_state.paciente_ativo = {"prontuario": id_p, "nome": dados['Paciente'], "mae": dados['Mãe']}
                    st.rerun()
            else: st.info("Sem registros.")
            st.markdown("</div>", unsafe_allow_html=True)
        with c2:
            st.markdown("<div class='input-card'><h3>➕ Novo Paciente</h3>", unsafe_allow_html=True)
            nn, nm, np = st.text_input("Nome:"), st.text_input("Mãe:"), st.text_input("Prontuário:")
            if st.button("Cadastrar") and nn and np:
                st.session_state.paciente_ativo = {"nome": nn, "mae": nm, "prontuario": str(np)}
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="patient-header"><div><p style="font-size:0.8rem;opacity:0.8;">PRONTUÁRIO ATIVO</p><h2>👤 {st.session_state.paciente_ativo["nome"]}</h2></div><div><p>Prontuário: <b>{st.session_state.paciente_ativo["prontuario"]}</b></p><button style="background:transparent;border:1px solid white;color:white;border-radius:5px;cursor:pointer;" onclick="window.location.reload();">Trocar Paciente</button></div></div>', unsafe_allow_html=True)
        tabs = st.tabs(["📊 Painel", "👁️ Visão", "🔄 Cushing", "💧 Fístula", "🚰 D.I.", "🧂 Sódio", "🦠 Meningite"])

        with tabs[0]: # Painel
            st.subheader("📊 Resultados Consolidados")
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
                            st.markdown(f'<div class="dashboard-card b-{cor}"><div style="font-weight:bold;">{r["Avaliação Clínica"]}</div><div class="card-value t-{cor}">{v}%</div><div style="font-weight:bold;" class="t-{cor}">{r["Classificação"]}</div><div style="font-size:0.7rem;color:#aaa;">{r["Data/Hora"]}</div></div><br>', unsafe_allow_html=True)
                else: st.info("Nenhum cálculo salvo.")

        with tabs[1]: # Visão
            st.markdown("<div class='input-card'><h4>👁️ Visão</h4>", unsafe_allow_html=True)
            v1, v2 = st.columns(2)
            with v1: vq = st.toggle("Compressão do quiasma?"); vd = st.toggle("Defeito difuso?")
            with v2: vm = st.number_input("Duração (meses):", 0); vmd = st.number_input("MD (dB):", 0.0)
            if st.button("Calcular e Salvar Visão"):
                res = risco_melhora_visual_ji_2023(vq, vd, vm, vmd)
                salvar_registro("Prognóstico Visual", res, "melhora"); st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        with tabs[6]: # Meningite (Zhou et al., 2025)
            st.markdown("<div class='input-card'><h4>🦠 Meningite Pós-operatória</h4>", unsafe_allow_html=True)
            m1, m2 = st.columns(2)
            with m1:
                dur = st.number_input("Duração Cirúrgica (h):", 0.0, step=0.1, help="Tempo total de procedimento (OR 2.68). [cite: 175]")
                fist = st.toggle("Fístula LCR Intraoperatória?", help="Fator de risco independente (OR 9.19). [cite: 17, 175]")
            with m2:
                diam = st.number_input("Diâmetro do Tumor (cm):", 0.0, step=0.1, help="A cada 1cm adicional, o risco sobe 2.7x. [cite: 175, 305]")
            if st.button("Calcular e Salvar Meningite"):
                res = risco_meningite_zhou_2025(dur, diam, fist)
                salvar_registro("Risco Meningite", res, "risco"); st.rerun()
            with st.expander("📚 Referência Científica"):
                st.markdown("**Zhou P, et al. (2025)**: Predictive model for meningitis after pituitary tumor resection... *Eur J Med Res*. [cite: 1, 2, 5, 20]")
            st.markdown("</div>", unsafe_allow_html=True)

# --- HISTÓRICO GERAL ---
elif nav == "⚙️ Histórico Geral":
    st.title("⚙️ Gerenciamento de Dados")
    if os.path.exists(ARQUIVO_CSV):
        df_g = pd.read_csv(ARQUIVO_CSV, dtype={'Prontuário': str})
        st.dataframe(df_g.sort_values(by="Data/Hora", ascending=False), use_container_width=True, hide_index=True)
        st.markdown("---")
        st.subheader("🗑️ Excluir Paciente")
        lista_d = [""] + [f"{r['Prontuário']} - {r['Paciente']}" for _, r in df_g.drop_duplicates(subset=['Prontuário']).iterrows()]
        del_p = st.selectbox("Selecione o registro para apagar permanentemente:", lista_d)
        if st.button("🚨 CONFIRMAR EXCLUSÃO") and del_p:
            id_d = del_p.split(" - ")[0]
            df_g[df_g['Prontuário'] != id_d].to_csv(ARQUIVO_CSV, index=False, encoding='utf-8')
            st.success(f"Paciente {id_d} removido."); st.rerun()

st.markdown("<div class='watermark'>By Vinícius Bacelar Ferreira</div>", unsafe_allow_html=True)
