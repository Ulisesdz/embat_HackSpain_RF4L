# Publicar en Vercel

La UI está en `dashboard/`. Las funciones de `api/` leen **tus** scores
(`data/features/`) y no recalculan el motor.

## 1. Sube el repo a GitHub

Desde la raíz, en este orden:

```bash
git add vercel.json .vercelignore api docs/DEPLOY.md
git add dashboard src/features/client_health_score
git add data/features/scores_finales.csv
git add data/features/scores_mensuales.csv
git add data/features/score_explanations.json
git status
```

Comprueba que **no** salgan `invoices.csv` ni `transactions.csv`.

Commit y push a GitHub (la rama que uses, normalmente `main`).

`scores_mensuales.csv` pesa ~16 MB. GitHub lo admite; no subas el dataset crudo.

## 2. Proyecto en Vercel

1. Entra en [vercel.com](https://vercel.com) con GitHub.
2. **Add New… → Project** e importa este repo.
3. Ajustes:
   - **Framework Preset:** Other
   - **Root Directory:** `.` (la raíz, no `dashboard`)
   - **Build Command:** vacío
   - **Output Directory:** `dashboard` (ya está en `vercel.json`)
   - **Install Command:** vacío (Vercel instala `api/requirements.txt` para las funciones)
4. **Environment Variables** (opcional): `GEMINI_API_KEY` si no quieres pegarla en la UI.
5. **Deploy**.

## 3. Qué tiene que verse

URL tipo `https://tu-proyecto.vercel.app/`

- Ficha con score real (no “Vista demo”).
- Selector con las ~1.280 empresas.
- **Cómo se calcula** al mismo ancho.
- **Generar con IA:** key en el diálogo o la variable de entorno.

Si sale “Vista demo”, las funciones no han llegado a `data/features/`. En Vercel → Deployment → Function logs.

## 4. Límites

Hobby suele cortar funciones a ~10–30 s. El primer arranque (pandas + CSV) puede ir justo. Si 500 por timeout, pasa el proyecto a Pro o reintenta: el siguiente request ya va en caliente.

No despliegues `python -m src.run`. El score se calcula en local; Vercel solo pinta y redacta.
