# Publicar en Vercel

**App:** [https://embat-hack-spain-rf-4-l.vercel.app/](https://embat-hack-spain-rf-4-l.vercel.app/)

La UI se edita en `frontend/`. `python -m src.build_dashboard` la copia a `dashboard/`, que es lo que publica Vercel. `api/` lee `data/features/` (scores ya calculados). No se ejecuta el motor en Vercel.

Si hay que volver a desplegar: el proyecto en Vercel apunta a la rama `main`. Framework Other, Output Directory `dashboard`. Variable opcional: `GEMINI_API_KEY`.
