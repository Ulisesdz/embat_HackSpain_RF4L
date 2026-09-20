export const AXIS_BLURBS: Record<string, string> = {
  deuda_comercial: "Pagos a proveedores sobre vencimientos. El componente de mayor peso.",
  liquidez: "Flujo operativo del trimestre relativo a ingresos.",
  colchon: "Meses de gasto cubiertos. La volatilidad del flujo reduce la nota.",
  trayectoria: "Dirección de flujo y deuda a 3 meses. No es el cambio del Health Score.",
  eficiencia: "Gasto por euro ingresado. 1,0 es el punto de equilibrio.",
  cobro_clientes: "Cobro sobre vencimientos. Pesa menos que proveedores: parte del riesgo es de contraparte.",
};

export const AXIS_ACTIONS: Record<string, string> = {
  deuda_comercial: "Revisar pagos vencidos a proveedores.",
  liquidez: "Adelantar cobros o recortar salidas no operativas.",
  colchon: "Elevar caja operativa hasta un mes de gasto.",
  trayectoria: "Revertir la pendiente de flujo y de deuda comercial.",
  eficiencia: "Reducir gasto por encima de ingresos.",
  cobro_clientes: "Cobrar vencido. No adelantar pagos propios.",
};

export const BANDS = [
  { min: 68, label: "Saludable" },
  { min: 52, label: "Estable" },
  { min: 42, label: "En riesgo" },
  { min: 33, label: "Frágil" },
  { min: 0, label: "Crítico" },
] as const;
