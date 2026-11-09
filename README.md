# IMPI — Asistente de soporte con IA

Asistente de soporte con IA para una plataforma de cálculo de bonos y comisiones.
Responde las dudas de cada cliente usando su propia documentación.
Proyecto de prácticas (Flask + SQLite + JWT + Claude).

## Ejecutar

```bash
pip install -r requirements.txt
cp .env.example .env     # en Windows: copy .env.example .env
python app.py            # http://localhost:5000
```

Usuario admin (se crea solo): **admin@impi.com / admin123**

## IA apagada por defecto

El `.env` trae `AI_ENABLED=false`: el chat funciona con una respuesta simulada y
**no consume tokens**. Para activarla, pon `AI_ENABLED=true` y tu `ANTHROPIC_API_KEY`.

## Notas

- Cada cliente tiene su carpeta `docs/<id>/`; sus archivos (`.md`, `.txt`, `.xlsx`)
  se usan como contexto. Un cliente nunca ve los datos de otro.
- No se versionan el `.env` ni `instance/impi.db`.
