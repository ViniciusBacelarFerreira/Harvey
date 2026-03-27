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
if 'ultimo_resultado' not in st.session_state:
    st.session_state.ultimo_resultado = None

ARQUIVO_CSV = "registro_pacientes.csv"
SENHA_CORRETA = "hugv1869"

# ==========================================
# FUNÇÕES DE CÁLCULO (BACK-END)
# ==========================================

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
    return ("Baixo Risco", "green") if prob < 10 else ("Risco Moderado", "orange") if prob < 25 else ("Alto Risco", "red")

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
    /* Uso de variáveis nativas do Streamlit para adaptação Dark/Light Mode automática */
    .login-box { 
        background-color: var(--secondary-background-color); 
        border-radius: 20px; 
        border: 1px solid rgba(128, 128, 128, 0.2); 
        padding: 40px; 
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1); 
        text-align: center; 
        max-width: 500px; 
        margin: auto; 
        color: var(--text-color);
    }
    
    .watermark { 
        position: fixed; 
        bottom: 20px; 
        right: 30px; 
        opacity: 0.5; 
        font-family: 'Georgia', serif; 
        font-style: italic; 
        font-size: 0.9rem; 
        pointer-events: none; 
        color: var(--text-color); 
    }
    
    .main-title { 
        background: -webkit-linear-gradient(45deg, #1565c0, #b8860b); 
        -webkit-background-clip: text; 
        -webkit-text-fill-color: transparent; 
        font-weight: 900; 
        font-size: 3.5rem; 
        text-align: center; 
    }
    
    .harvey-text { font-family: 'Georgia', serif; font-style: italic; color: #b8860b; margin-left: 10px; }
    
    .patient-header { 
        background-color: var(--secondary-background-color); 
        border: 1px solid rgba(128,128,128,0.2); 
        color: var(--text-color); 
        padding: 20px; 
        border-radius: 15px; 
        margin-bottom: 20px; 
        display: flex; 
        justify-content: space-between; 
        align-items: center;
    }
    
    .dashboard-card { 
        background-color: var(--secondary-background-color); 
        border-radius: 15px; 
        padding: 20px; 
        box-shadow: 0 4px 12px rgba(0,0,0,0.1); 
        text-align: center; 
        border-top: 6px solid #ddd; 
        color: var(--text-color); 
        transition: transform 0.2s; 
    }
    .dashboard-card:hover { transform: translateY(-5px); }
    .card-value { font-size: 2.8rem; font-weight: 800; margin: 5px 0; }
    
    .b-green { border-top-color: #2e7d32 !important; } .t-green { color: #2e7d32 !important; }
    .b-orange { border-top-color: #ef6c00 !important; } .t-orange { color: #ef6c00 !important; }
    .b-red { border-top-color: #c62828 !important; } .t-red { color: #c62828 !important; }
    
    .input-card { 
        background-color: var(--secondary-background-color); 
        padding: 30px; 
        border-radius: 15px; 
        box-shadow: 0 4px 20px rgba(0,0,0,0.05); 
        margin-top: 20px; 
        color: var(--text-color); 
        border: 1px solid rgba(128, 128, 128, 0.2); 
    }
    
    .calc-info { 
        background-color: rgba(21, 101, 192, 0.1); 
        padding: 12px; 
        border-radius: 8px; 
        border-left: 5px solid #1565c0; 
        margin-bottom: 20px; 
        font-size: 0.95rem; 
        color: var(--text-color); 
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# TELA DE LOGIN
# ==========================================
if not st.session_state.autenticado:
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<div class='login-box'>", unsafe_allow_html=True)
        st.markdown("<h1 class='main-title' style='font-size: 2.8rem;'>NeuroPreditor <span class='harvey-text'>Harvey</span></h1>", unsafe_allow_html=True)
        st.markdown("<p style='font-size: 1rem; opacity: 0.8;'>Acesso Restrito - Hospital Universitário Getúlio Vargas</p>", unsafe_allow_html=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        senha = st.text_input("Senha Institucional:", type="password", placeholder="Insira a senha...")
        if st.button("DESBLOQUEAR ACESSO", use_container_width=True):
            if senha == SENHA_CORRETA:
                st.session_state.autenticado = True
                st.rerun()
            else: 
                st.error("Senha incorreta. Tente novamente.")
        
        st.markdown("<hr style='opacity: 0.2; margin: 25px 0;'>", unsafe_allow_html=True)
        st.markdown("<p style='font-size: 0.9rem; font-weight: bold; opacity: 0.8;'>✨ Made By Vinícius Bacelar Ferreira</p>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
        
    st.stop()

# ==========================================
# NAVEGAÇÃO / MENU LATERAL
# ==========================================
with st.sidebar:
    st.markdown("<div style='text-align: center;'>", unsafe_allow_html=True)
    st.markdown("<h4 style='color: #1565c0; margin-top: 5px;'>HUGV - UFAM</h4>", unsafe_allow_html=True)
    st.markdown("<h2 style='color: #1565c0; margin-top: 15px;'>Harvey</h2>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
    
    st.markdown("---")
    nav = st.radio("Navegação:", ["🏠 Área de Trabalho", "⚙️ Histórico Geral"])
    
    if st.session_state.paciente_ativo['prontuario']:
        st.markdown("---")
        if st.button("❌ Fechar Prontuário Atual", type="primary"):
            st.session_state.paciente_ativo = {"nome": "", "mae": "", "prontuario": ""}
            st.session_state.ultimo_resultado = None
            st.rerun()

    st.markdown("---")
    with st.expander("🌓 Tema (Claro/Escuro)"):
        st.write("O sistema adapta-se automaticamente à preferência do seu dispositivo. Para alterar manualmente, clique no **Menu (⋮)** no canto superior direito da tela > **Settings** > **Theme**.")
    
    st.markdown("<br><p style='text-align: center; font-size: 0.8rem; font-weight: bold; opacity: 0.7;'>Made By Vinícius Bacelar Ferreira</p>", unsafe_allow_html=True)
    
    st.markdown("---")
    if st.button("🚪 Sair do Sistema"):
        st.session_state.autenticado = False
        st.session_state.paciente_ativo = {"nome": "", "mae": "", "prontuario": ""}
        st.rerun()

# ==========================================
# ÁREA DE TRABALHO
# ==========================================
if nav == "🏠 Área de Trabalho":
    if not st.session_state.paciente_ativo['prontuario']:
        st.markdown("<h1 class='main-title'>NeuroPreditor <span class='harvey-text'>Harvey</span></h1>", unsafe_allow_html=True)
        st.markdown("<div class='input-card' style='text-align: center;'><p style='font-size:1.2rem; font-style:italic;'>\"Gostaria de ver o dia em que alguém fosse nomeado cirurgião sem ter mãos, pois a parte operatória é a menor parte do trabalho.\"</p><p style='color:#b8860b; font-weight:800;'>— HARVEY WILLIAMS CUSHING</p></div>", unsafe_allow_html=True)
        
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
            else: st.info("Sem registros no momento.")
            st.markdown("</div>", unsafe_allow_html=True)
            
        with c2:
            st.markdown("<div class='input-card'><h3>➕ Novo Paciente</h3>", unsafe_allow_html=True)
            nn = st.text_input("Nome:")
            nm = st.text_input("Nome da Mãe:")
            np = st.text_input("Prontuário:")
            if st.button("Cadastrar") and nn and np:
                st.session_state.paciente_ativo = {"nome": nn, "mae": nm, "prontuario": str(np)}
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="patient-header"><div><p style="font-size:0.8rem;opacity:0.8;margin-bottom:0;">PRONTUÁRIO ATIVO</p><h2 style="margin-top:0;">👤 {st.session_state.paciente_ativo["nome"]}</h2></div><div><p style="margin-bottom:0;">Prontuário: <b>{st.session_state.paciente_ativo["prontuario"]}</b></p></div></div>', unsafe_allow_html=True)
        tabs = st.tabs(["📊 Painel Visual", "👁️ Visão", "🔄 Cushing", "💧 Fístula", "🚰 D.I.", "🧂 Sódio", "🦠 Meningite", "📄 Relatório A4"])

        with tabs[0]: 
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
                        st.markdown(f'<div class="dashboard-card b-{cor}"><div style="font-weight:bold; opacity:0.8;">{r["Avaliação Clínica"]}</div><div class="card-value t-{cor}">{v}%</div><div style="font-weight:bold;" class="t-{cor}">{r["Classificação"]}</div><div style="font-size:0.7rem;opacity:0.6;">{r["Data/Hora"]}</div></div><br>', unsafe_allow_html=True)
                else: st.info("Nenhum cálculo salvo.")

        with tabs[1]: 
            st.markdown("<div class='input-card'><h4>👁️ Visão</h4>", unsafe_allow_html=True)
            v1, v2 = st.columns(2)
            with v1: vq = st.toggle("Compressão do quiasma?"); vd = st.toggle("Defeito difuso?")
            with v2: vm = st.number_input("Duração (meses):", 0); vmd = st.number_input("MD (dB) pré-op:", 0.0)
            if st.button("Calcular e Salvar Visão"):
                res = risco_melhora_visual_ji_2023(vq, vd, vm, vmd)
                params = f"Compressão Quiasma: {'Sim' if vq else 'Não'} | Defeito Difuso: {'Sim' if vd else 'Não'} | Sintomas: {vm} meses | MD: {vmd} dB"
                salvar_registro("Prognóstico Visual", res, "melhora", params); st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
    
        with tabs[2]: 
            st.markdown("<div class='input-card'><h4>🔄 Cushing</h4>", unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            with c1: cd = st.number_input("Meses sintomas:", 0, key="c1"); cc = st.toggle("Cirurgia prévia?")
            with c2: ch = st.select_slider("Hardy:", [0,1,2,3,4], value=2); cl = st.selectbox("Localização:", ["Bilateral","Direita","Esquerda","Central","Haste"])
            if st.button("Calcular Cushing"):
                res = risco_recorrencia_cushing_cuper_2025(cd, ch, cl, cc)
                params = f"Sintomas: {cd} meses | Cirurgia Prévia: {'Sim' if cc else 'Não'} | Grau Hardy: {ch} | Localização: {cl}"
                salvar_registro("Recorrência Cushing", res, "risco", params); st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        with tabs[3]: 
            st.markdown("<div class='input-card'><h4>💧 Fístula LCR</h4>", unsafe_allow_html=True)
            f1, f2 = st.columns(2)
            with f1: fk = st.toggle("Kelly ≥ 2?"); fs = st.toggle("Suprasselar ≥ B?")
            with f2: fp = st.toggle("Pneumoencéfalo ≥ 3?"); fj = st.number_input("Janela (mm):", 0.0)
            if st.button("Calcular Fístula"):
                res = risco_fistula_lcr_zhang_2025(fk, fs, fp, fj)
                params = f"Kelly ≥ 2: {'Sim' if fk else 'Não'} | Supra ≥ B: {'Sim' if fs else 'Não'} | Pneumoencéfalo ≥ 3: {'Sim' if fp else 'Não'} | Janela óssea: {fj} mm"
                salvar_registro("Risco Fístula LCR", res, "risco", params); st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        with tabs[4]: 
            st.markdown("<div class='input-card'><h4>🚰 Diabetes Insipidus</h4>", unsafe_allow_html=True)
            d1, d2 = st.columns(2)
            with d1: dd = st.checkbox("DM?"); dh = st.checkbox("HAS?"); dc = st.checkbox("Cardio?")
            with d2: dco = st.number_input("Cortisol:", 0.0); df_ = st.toggle("Fístula?"); dr = st.toggle("Rígido?")
            if st.button("Calcular D.I."):
                res = risco_diabetes_insipidus_li_2024(dd, dh, dc, dco, df_, dr)
                params = f"DM: {'Sim' if dd else 'Não'} | HAS: {'Sim' if dh else 'Não'} | Cardio: {'Sim' if dc else 'Não'} | Cortisol: {dco} | Fístula: {'Sim' if df_ else 'Não'} | Tumor Rígido: {'Sim' if dr else 'Não'}"
                salvar_registro("Diabetes Insipidus", res, "risco", params); st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        with tabs[5]: 
            st.markdown("<div class='input-card'><h4>🧂 Hiponatremia (DPH)</h4>", unsafe_allow_html=True)
            mod_h = st.radio("Modelo:", ["Cai (Sangue)", "Tan (RM)"])
            hp12 = st.toggle("Hipo D1-D2?")
            if mod_h == "Cai (Sangue)":
                mo = st.number_input("Monócitos %:", 0.0); pt = st.number_input("PT (seg):", 0.0)
                if st.button("Calcular DPH (Cai)"):
                    res = risco_pdh_cai_2023(hp12, mo, pt)
                    params = f"Hipo D1-D2: {'Sim' if hp12 else 'Não'} | Monócitos: {mo}% | PT: {pt} seg"
                    salvar_registro("DPH (Cai)", res, "risco", params); st.rerun()
            else:
                pr = st.number_input("PRL pré-op:", 0.0); dia = st.number_input("Diafragma (mm):", 0.0)
                if st.button("Calcular DPH (Tan)"):
                    res = risco_pdh_tan_2025(pr, dia, hp12)
                    params = f"Hipo D1-D2: {'Sim' if hp12 else 'Não'} | Prolactina: {pr} ng/mL | Elevação Diafragma: {dia} mm"
                    salvar_registro("DPH (Tan)", res, "risco", params); st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        with tabs[6]: 
            st.markdown("<div class='input-card'><h4>🦠 Meningite Pós-operatória</h4>", unsafe_allow_html=True)
            m1, m2 = st.columns(2)
            with m1: md = st.number_input("Duração (h):", 0.0); mf = st.toggle("Fístula intraop?")
            with m2: mt = st.number_input("Diâmetro (cm):", 0.0)
            if st.button("Calcular Meningite"):
                res = risco_meningite_zhou_2025(md, mt, mf)
                params = f"Duração: {md} h | Diâmetro: {mt} cm | Fístula Intraop: {'Sim' if mf else 'Não'}"
                salvar_registro("Risco Meningite", res, "risco", params); st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
            
        # --- RELATÓRIO A4 HTML IMPRIMÍVEL ---
        with tabs[7]:
            st.markdown("### 🖨️ Relatório (Tamanho A4)")
            st.info("Clique no botão abaixo para imprimir. Ative os **Gráficos de segundo plano** nas opções de impressão do navegador para manter as cores do cabeçalho.")
            
            linhas_html = ""
            if os.path.exists(ARQUIVO_CSV):
                df_rel = pd.read_csv(ARQUIVO_CSV, dtype={'Prontuário': str})
                df_rel_pac = df_rel[df_rel['Prontuário'] == str(st.session_state.paciente_ativo['prontuario'])]
                
                if not df_rel_pac.empty:
                    df_latest_rel = df_rel_pac.sort_values(by="Data/Hora").groupby("Avaliação Clínica").last().reset_index()
                    for _, r in df_latest_rel.iterrows():
                        param_str = r.get("Parâmetros Inseridos", "Parâmetros antigos")
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
                .print-button {{ background: #0b2e59; color: white; border: none; padding: 12px 25px; border-radius: 8px; font-weight: bold; font-size: 16px; cursor: pointer; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); width: 100%; }}
                .print-button:hover {{ background: #1565c0; }}
                .a4-page {{ width: 210mm; min-height: 297mm; background: white; padding: 20mm; box-sizing: border-box; box-shadow: 0 0 15px rgba(0,0,0,0.2); position: relative; color: black; }}
                .header {{ border-bottom: 3px solid #0b2e59; padding-bottom: 15px; margin-bottom: 25px; text-align: center; }}
                .header h1 {{ margin: 0; color: #0b2e59; font-size: 26px; text-transform: uppercase; }}
                .header h3 {{ margin: 5px 0 0 0; color: #555; font-size: 14px; font-weight: normal; }}
                .patient-box {{ background: #f4f7f6; border: 1px solid #ddd; padding: 15px; border-radius: 8px; margin-bottom: 30px; }}
                .patient-box p {{ margin: 5px 0; font-size: 14px; color: #333; }}
                .section-title {{ font-size: 18px; color: #0b2e59; border-bottom: 1px solid #ccc; padding-bottom: 5px; margin-bottom: 15px; font-weight: bold; }}
                table {{ width: 100%; border-collapse: collapse; margin-bottom: 30px; }}
                th, td {{ border: 1px solid #ddd; padding: 12px; font-size: 13px; }}
                th {{ background-color: #0b2e59; color: white; text-align: center; font-weight: bold; }}
                .footer {{ position: absolute; bottom: 20mm; left: 20mm; right: 20mm; border-top: 1px solid #ccc; padding-top: 10px; text-align: center; font-size: 11px; color: #777; }}
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
                        <button class="print-button" onclick="window.print()">🖨️ IMPRIMIR RELATÓRIO</button>
                    </div>
                    <div class="a4-page">
                        <div class="header">
                            <h1>Hospital Universitário Getúlio Vargas</h1>
                            <h3>NeuroPreditor Harvey - Relatório de Avaliação Preditiva Transesfenoidal</h3>
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
                                <th style="width: 20%;">Módulo Clínico</th>
                                <th style="width: 45%;">Parâmetros Inseridos</th>
                                <th style="width: 15%;">Resultado</th>
                                <th style="width: 20%;">Classificação</th>
                            </tr>
                            {linhas_html if linhas_html else '<tr><td colspan="4" style="text-align:center; color: #333;">Nenhuma avaliação realizada até o momento.</td></tr>'}
                        </table>
                        
                        <div style="font-size: 11px; color: #666; text-align: justify;">
                            <b>Aviso Clínico:</b> Este documento reflete as estimativas de probabilidade baseadas nos dados inseridos e em modelos preditivos validados na literatura internacional (Nomogramas). Estes resultados destinam-se a apoiar a tomada de decisão médica e não substituem o julgamento clínico individualizado do neurocirurgião ou endocrinologista responsável.
                        </div>
                        
                        <div class="footer">
                            <p style="margin: 0;">NeuroPreditor Harvey • HUGV - UFAM</p>
                            <p style="margin: 5px 0 0 0; font-style: italic;">Made by Vinícius Bacelar Ferreira</p>
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
    st.title("⚙️ Gerenciamento de Dados")
    if os.path.exists(ARQUIVO_CSV):
        df_g = pd.read_csv(ARQUIVO_CSV, dtype={'Prontuário': str})
        st.dataframe(df_g.sort_values(by="Data/Hora", ascending=False), use_container_width=True, hide_index=True)
        st.download_button("📥 Exportar Planilha Completa", df_g.to_csv(index=False).encode('utf-8'), "historico_neuro.csv", "text/csv")
        st.markdown("---")
        st.subheader("🗑️ Excluir Paciente")
        lista_d = [""] + [f"{r['Prontuário']} - {r['Paciente']}" for _, r in df_g.drop_duplicates(subset=['Prontuário']).iterrows()]
        del_sel = st.selectbox("Selecione o paciente para apagar permanentemente:", lista_d)
        if st.button("🚨 CONFIRMAR EXCLUSÃO") and del_sel:
            id_d = del_sel.split(" - ")[0]
            df_g[df_g['Prontuário'] != id_d].to_csv(ARQUIVO_CSV, index=False, encoding='utf-8')
            st.success("Registro removido com sucesso."); st.rerun()
    else: st.info("Nenhum dado registrado.")

# Marca d'água invisível que não quebra o layout
st.markdown("<div class='watermark'>By Vinícius Bacelar Ferreira</div>", unsafe_allow_html=True)
