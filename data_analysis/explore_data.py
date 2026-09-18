import pandas as pd
import os

def explorar_balances_y_deuda():
    data_path = "data/"
    reporte = ["=== RESUMEN EXPLORATORIO: CAJA, DEUDA Y MOROSIDAD ===\n"]

    try:
        balances = pd.read_csv(os.path.join(data_path, "balances.csv"))
        banking = pd.read_csv(os.path.join(data_path, "banking_products.csv"))
        debt = pd.read_csv(os.path.join(data_path, "debt_products.csv"))
        invoices = pd.read_csv(os.path.join(data_path, "invoices.csv"))
    except FileNotFoundError as e:
        print(f"Error cargando archivos: {e}")
        return

    # 1. CAJA REAL (Balances a 1 de septiembre de 2026)
    reporte.append("--- FOTO FINAL DE CAJA (BALANCES) ---")
    # Unir balances con banking products para filtrar solo cuentas corrientes/ahorro
    caja = pd.merge(balances, banking[['product_id', 'type']], on='product_id', how='inner')
    caja_por_empresa = caja.groupby('company_id')['balance'].sum()
    
    reporte.append(f"Empresas con saldo en cuenta reportado: {len(caja_por_empresa)}")
    reporte.append(f"Saldo medio en caja: {caja_por_empresa.mean():,.2f}")
    reporte.append(f"Empresas en NÚMEROS ROJOS (saldo total negativo): {len(caja_por_empresa[caja_por_empresa < 0])}\n")

    # 2. DEUDA VIVA
    reporte.append("--- DEUDA VIVA BANCARIA (OUTSTANDING) ---")
    deuda_por_empresa = debt.groupby('company_id')['outstanding'].sum()
    reporte.append(f"Empresas con deuda bancaria viva: {len(deuda_por_empresa)}")
    reporte.append(f"Deuda pendiente media por empresa: {deuda_por_empresa.mean():,.2f}\n")

    # 3. EL RATIO CRÍTICO: PORCENTAJE DE DINERO ATRAPADO
    reporte.append("--- RATIO DE FACTURAS VENCIDAS ---")
    # Suma del dinero total de facturas emitidas/recibidas vs dinero pendiente en status overdue
    facturacion_total = invoices.groupby('company_id')['amount'].sum()
    overdue_invoices = invoices[invoices['status'] == 'overdue']
    deuda_comercial = overdue_invoices.groupby('company_id')['pending_amount'].sum()
    
    # Cruzamos para calcular el porcentaje
    df_inv = pd.DataFrame({'total': facturacion_total, 'overdue': deuda_comercial}).fillna(0)
    # Evitar división por cero
    df_inv['pct_atrapado'] = (df_inv['overdue'] / df_inv['total'].replace(0, 1)) * 100
    
    reporte.append(f"Media del volumen facturado que está 'overdue': {df_inv['pct_atrapado'].mean():.1f}%")
    reporte.append(f"Empresas con >30% del dinero atrapado (Riesgo Alto): {len(df_inv[df_inv['pct_atrapado'] > 30])}\n")

    report_str = "\n".join(reporte)
    with open("resumen_datos.txt", "w", encoding="utf-8") as f:
        f.write(report_str)
        
    print(report_str)

if __name__ == "__main__":
    explorar_balances_y_deuda()