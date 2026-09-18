import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

st.set_page_config(page_title="Embat X-Ray: Agente Proactivo", layout="wide")

# Cargar los datos puntuados
@st.cache_data
def load_data():
    df = pd.read_csv('data/master_panel_scored.csv')
    return df

df = load_data()

# --- HEADER Y PRODUCTO ---
st.title("⚡ HackSpain X-Ray: Agente Financiero Proactivo")
st.markdown("""
**Producto:** Una herramienta SaaS para CFOs y Bancos. No solo da un número, sino que lee el 
comportamiento de caja y pagos para avisar *antes* de que haya problemas de liquidez.
""")

# --- SELECTOR DE EMPRESA ---
empresas = df['company_id'].unique()
empresa_seleccionada = st.selectbox("Selecciona una empresa para analizar:", empresas)

datos_empresa = df[df['company_id'] == empresa_seleccionada].sort_values('year_month_str')

if not datos_empresa.empty:
    # Obtener el mes actual y el anterior
    ultimo_mes = datos_empresa.iloc[-1]
    mes_anterior = datos_empresa.iloc[-2] if len(datos_empresa) > 1 else ultimo_mes
    
    score_actual = ultimo_mes['score']
    delta_score = score_actual - mes_anterior['score']
    
    # --- PANEL SUPERIOR (KPIs) ---
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Score de Salud Actual", f"{score_actual:.0f} / 100", f"{delta_score:.0f} pts vs mes anterior")
    col2.metric("Flujo Neto (Último Mes)", f"€ {ultimo_mes['flujo_neto']:,.0f}")
    col3.metric("Retraso en Pagos", f"{ultimo_mes['retraso_medio']:.1f} días", 
                f"{(ultimo_mes['retraso_medio'] - mes_anterior['retraso_medio']):.1f} días vs ant", delta_color="inverse")
    col4.metric("Burn Ratio", f"{ultimo_mes['burn_ratio']:.2f}x", "1.0x es el límite seguro")

    st.divider()

    # --- EXPLICABILIDAD Y ALERTAS (MOTOR DE REGLAS) ---
    st.subheader("🤖 Explicación y Recomendación del Agente")
    
    if score_actual >= 75:
        st.success("**Diagnóstico:** Empresa muy sólida. Flujos estables y pagadora puntual.")
        st.info("**Oportunidad (Para el Banco):** Ofrecer productos de inversión o mejorar condiciones de crédito para fidelizar.")
    elif score_actual >= 50:
        st.warning("**Diagnóstico:** Situación estable, pero con métricas estancadas.")
    else:
        st.error("**Diagnóstico:** Riesgo de Liquidez Detectado. Deterioro estructural.")
        
        # Generar explicaciones basadas en los features
        razones = []
        if ultimo_mes['flujo_neto_3m_avg'] < 0:
            razones.append("- Lleva de media 3 meses quemando caja estructuralmente.")
        if ultimo_mes['retraso_medio'] > 5:
            razones.append(f"- Se está retrasando {ultimo_mes['retraso_medio']:.1f} días en pagar, señal de tensión de tesorería.")
        if ultimo_mes['usage_ratio'] > 80:
            razones.append("- Tiene sus líneas de crédito bancarias al límite.")
            
        for r in razones:
            st.write(r)
            
        st.info("**Recomendación (Para el CFO):** Renegociar vencimientos de facturas de inmediato o aplicar factoring sobre las cuentas a cobrar.")

    st.divider()

    # --- GRÁFICO DE TRAYECTORIA ---
    st.subheader("📈 Trayectoria (Señal Anticipada)")
    fig, ax1 = plt.subplots(figsize=(12, 4))
    
    # Eje 1: Score
    color = 'tab:blue'
    ax1.set_xlabel('Mes')
    ax1.set_ylabel('Score Financiero', color=color)
    ax1.plot(datos_empresa['year_month_str'], datos_empresa['score'], marker='o', color=color, linewidth=2)
    ax1.tick_params(axis='y', labelcolor=color)
    ax1.set_ylim(0, 100)
    plt.xticks(rotation=45)
    
    # Eje 2: Retraso en Pagos (como indicador adelantado)
    ax2 = ax1.twinx()  
    color = 'tab:red'
    ax2.set_ylabel('Días de Retraso Medio', color=color)  
    ax2.bar(datos_empresa['year_month_str'], datos_empresa['retraso_medio'], alpha=0.3, color=color)
    ax2.tick_params(axis='y', labelcolor=color)
    
    plt.title("Evolución del Score vs Comportamiento de Pago")
    st.pyplot(fig)