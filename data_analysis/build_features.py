import pandas as pd
import numpy as np
import os

def construir_features_robustas():
    data_path = "data/"
    print("Cargando datos y filtrando ventana temporal (Sept 2024 - Sept 2026)...")
    
    tx = pd.read_csv(os.path.join(data_path, "transactions.csv"))
    inv = pd.read_csv(os.path.join(data_path, "invoices.csv"))
    
    tx['date'] = pd.to_datetime(tx['date'], errors='coerce')
    inv['due_date'] = pd.to_datetime(inv['due_date'], errors='coerce')
    
    # Filtro estricto de 24 meses
    fecha_inicio = pd.to_datetime("2024-09-01")
    fecha_fin = pd.to_datetime("2026-09-30")
    tx = tx[(tx['date'] >= fecha_inicio) & (tx['date'] <= fecha_fin)].copy()
    inv = inv[(inv['due_date'] >= fecha_inicio) & (inv['due_date'] <= fecha_fin)].copy()
    
    tx['year_month'] = tx['date'].dt.to_period('M')
    inv['year_month'] = inv['due_date'].dt.to_period('M')

    print("Calculando Base 1: Caja y Burn Rate...")
    # 1. CAJA: Ingresos, Gastos y Flujo Neto
    monthly_tx = tx.groupby(['company_id', 'year_month']).agg(
        caja_ingresos=('amount', lambda x: x[x > 0].sum()),
        caja_gastos=('amount', lambda x: abs(x[x < 0].sum())),
        flujo_neto=('amount', 'sum')
    ).reset_index()

    # NUEVO: Burn Rate (Gastos / Ingresos)
    # Si ingresan 0 y gastan, penalizamos con un ratio alto (e.g. 5.0) para reflejar quema pura de liquidez
    monthly_tx['burn_rate'] = np.where(monthly_tx['caja_ingresos'] > 0, 
                                       monthly_tx['caja_gastos'] / monthly_tx['caja_ingresos'], 
                                       np.where(monthly_tx['caja_gastos'] > 0, 5.0, 0))

    print("Calculando Base 2: Morosidad Bifurcada (Clientes/Proveedores)...")
    # 2. MOROSIDAD (Clientes vs Proveedores)
    inv['is_receivable'] = inv['amount'] > 0
    inv['amount_abs'] = inv['amount'].abs()
    inv['pending_abs'] = inv['pending_amount'].abs()
    
    inv_overdue = inv[inv['status'] == 'overdue']
    
    # Clientes (Ventas)
    inv_ventas = inv[inv['is_receivable']]
    mensual_ventas = inv_ventas.groupby(['company_id', 'year_month'])['amount_abs'].sum().reset_index(name='ventas_totales')
    mensual_atrapado_clientes = inv_overdue[inv_overdue['is_receivable']].groupby(['company_id', 'year_month'])['pending_abs'].sum().reset_index(name='ventas_atrapadas')
    
    # Proveedores (Compras)
    inv_compras = inv[~inv['is_receivable']]
    mensual_compras = inv_compras.groupby(['company_id', 'year_month'])['amount_abs'].sum().reset_index(name='compras_totales')
    mensual_atrapado_prov = inv_overdue[~inv_overdue['is_receivable']].groupby(['company_id', 'year_month'])['pending_abs'].sum().reset_index(name='compras_atrapadas')

    # 3. CONSOLIDACIÓN EN MASTER PANEL
    panel = pd.merge(monthly_tx, mensual_ventas, on=['company_id', 'year_month'], how='outer')
    panel = pd.merge(panel, mensual_atrapado_clientes, on=['company_id', 'year_month'], how='outer')
    panel = pd.merge(panel, mensual_compras, on=['company_id', 'year_month'], how='outer')
    panel = pd.merge(panel, mensual_atrapado_prov, on=['company_id', 'year_month'], how='outer')
    
    panel = panel.fillna(0)
    
    panel['pct_clientes_morosos'] = np.where(panel['ventas_totales'] > 0, 
                                             (panel['ventas_atrapadas'] / panel['ventas_totales']) * 100, 0)
    panel['pct_impagos_prov'] = np.where(panel['compras_totales'] > 0, 
                                         (panel['compras_atrapadas'] / panel['compras_totales']) * 100, 0)
    
    # Ordenamos antes de aplicar Medias Móviles
    panel = panel.sort_values(['company_id', 'year_month'])

    print("Calculando Base 3: Tendencias Temporales (Suavizado de Baches)...")
    # Medias Móviles de 3 meses (El corazón de la "Trayectoria")
    # Nos permite saber si un mes malo es un bache (media de 3 meses sigue bien) o una caída
    panel['flujo_neto_3m_avg'] = panel.groupby('company_id')['flujo_neto'].transform(lambda x: x.rolling(window=3, min_periods=1).mean())
    panel['impagos_prov_3m_avg'] = panel.groupby('company_id')['pct_impagos_prov'].transform(lambda x: x.rolling(window=3, min_periods=1).mean())
    panel['clientes_morosos_3m_avg'] = panel.groupby('company_id')['pct_clientes_morosos'].transform(lambda x: x.rolling(window=3, min_periods=1).mean())
    
    # Indicador de Deterioro Rápido (Delta vs mes anterior)
    # ¿Ha empeorado mucho respecto al mes pasado?
    panel['cambio_burn_rate'] = panel.groupby('company_id')['burn_rate'].diff().fillna(0)
    
    # Guardamos el dataset enriquecido
    output_path = os.path.join(data_path, "master_panel_clean.csv")
    panel.to_csv(output_path, index=False)
    print(f"\n Panel Maestro (Features) guardado en: {output_path} ({len(panel)} filas)")
    
    # 4. VERIFICACIÓN FINAL
    empresa_test = panel['company_id'].value_counts().index[0] 
    historia = panel[panel['company_id'] == empresa_test]
    
    print(f"\n--- TRAYECTORIA ENRIQUECIDA: {empresa_test} ---")
    columnas_vista = ['year_month', 'flujo_neto_3m_avg', 'burn_rate', 'pct_impagos_prov', 'impagos_prov_3m_avg']
    print(historia[columnas_vista].to_string(index=False))

if __name__ == "__main__":
    construir_features_robustas()