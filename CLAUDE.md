# IMPI — Contexto para Claude Code

Aplicación web de **soporte con IA** para una plataforma de cálculo de bonos y
comisiones (se opera con funciones T-SQL, datos por CSV). Cada cliente tiene su
documentación y el asistente responde usando **solo la de ese cliente**.
Proyecto de prácticas: mantener **simple y funcional**.

## Stack
Flask + SQLite (SQLAlchemy) · JWT (flask-jwt-extended) + Werkzeug · Claude Haiku
(desacoplada) · HTML/CSS/JS vanilla · openpyxl, python-dotenv.

## Estructura
- `app.py` — backend completo (monolítico): config, modelos, rutas, IA.
- `templates/` — `login.html`, `admin.html`, `chat.html`, `cambiar_password.html`.
- `static/css/base.css` · `static/js/i18n.js` (i18n ES/PT/EN).
- `docs/<id>/` — documentos por cliente (contexto) · `instance/impi.db` — BD (se crea sola).

## Ejecutar
`pip install -r requirements.txt` → `cp .env.example .env` → `python app.py`
(http://localhost:5000). Admin: `admin@impi.com` / `admin123`.
IA apagada por defecto (`AI_ENABLED=false`): responde simulado, sin gastar tokens.

## Decisiones clave
- **IA desacoplada** en `llamar_claude()` + interruptor `AI_ENABLED`: se puede cambiar
  de modelo o usar la pasarela de la empresa sin tocar lo demás.
- **Contexto por cliente:** lee `docs/<id>/` (.md/.txt/.xlsx; los .pdf aún no). Solo se
  envían los **últimos 8 mensajes** (ahorro de tokens).
- **Aislamiento:** todo se filtra por el `cliente_id` del JWT.
- **Control de tokens:** `limite_tokens` y `nivel_respuesta` por cliente; bloquea al tope.
- **Auto-migración:** `init_db()` agrega columnas nuevas sin perder la BD.
- **i18n:** `i18n.js` debe cargar ANTES de los scripts inline; si falta un `id` que el JS
  busca, el script se rompe entero.

## Hecho
Auth + roles · panel admin (clientes, documentos, historial, tokens) · chat del cliente ·
integración IA (modo prueba) · contexto por cliente · control de tokens · multi-idioma ·
cambio de contraseña forzado.

## Falta
Documentación general (ámbito común) · leer PDFs · pasarela de IA de la empresa ·
RAG con embeddings · panel de métricas · tests automatizados.

## Convenciones
Código y comentarios en español (sin tildes dentro del código Python; la UI sí lleva
tildes vía i18n). Paleta azul `#185FA5`. Entregas semanales por módulo a Git.

## Avances
S1–2 propuesta ✅ · S3 base (BD, login, roles) ✅ · S4–5 panel admin ✅ ·
S6–7 chat + base de conocimiento ✅ · S8–9 integración IA ✅ ·
S10 tokens 🔜 · S11 idiomas 🔜 · S12 seguridad 🔜 · S13 pruebas 🔜 ·
S14 documentación 🔜 · S15 entrega final 🔜
