# IMPI - Contexto para Claude Code

Aplicación web de soporte con IA para una plataforma de cálculo de bonos y
comisiones (se opera con funciones T-SQL, datos por CSV). Cada cliente tiene su
documentación y el asistente responde usando solo la de ese cliente.
Proyecto de prácticas: mantener simple y funcional.

## Stack
Flask + SQLite (SQLAlchemy), JWT (flask-jwt-extended) + Werkzeug, Claude Haiku
(desacoplada), HTML/CSS/JS vanilla, openpyxl, python-dotenv.

## Estructura
- app.py: backend completo (monolítico): config, modelos, rutas, IA.
- templates/: login.html, admin.html, chat.html, cambiar_password.html.
- static/css/base.css y static/js/i18n.js (i18n ES/PT/EN).
- docs/<id>/: documentos por cliente (contexto). instance/impi.db: base de datos (se crea sola).

## Ejecutar
pip install -r requirements.txt, luego copiar .env.example como .env, luego python app.py
(http://localhost:5000). Admin por defecto: admin@impi.com / admin123.
IA apagada por defecto (AI_ENABLED=false): responde simulado, sin gastar tokens.

## Decisiones clave
- IA desacoplada en la función llamar_claude() con el interruptor AI_ENABLED: se puede
  cambiar de modelo o usar la pasarela de la empresa sin tocar lo demás.
- Contexto por cliente: lee docs/<id>/ (.md, .txt, .xlsx; los .pdf aún no). Solo se
  envían los últimos 8 mensajes de la conversación (ahorro de tokens).
- Aislamiento: todo se filtra por el cliente_id del JWT.
- Control de tokens: limite_tokens y nivel_respuesta por cliente; bloquea al llegar al tope.
- Auto-migración: init_db() agrega columnas nuevas sin perder la base de datos.
- i18n: i18n.js debe cargar antes de los scripts inline; si falta un id que el JS busca,
  el script se rompe entero.

## Hecho
Autenticación y roles, panel de administración (clientes, documentos, historial, tokens),
chat del cliente, integración con la IA (modo prueba), contexto por cliente, control de
tokens, multi-idioma, cambio de contraseña forzado.

## Falta
Documentación general (ámbito común), leer PDFs, pasarela de IA de la empresa,
RAG con embeddings, panel de métricas, tests automatizados.

## Convenciones
Código y comentarios en español (sin tildes dentro del código Python; la interfaz sí
lleva tildes vía i18n). Paleta azul 185FA5. Entregas semanales por módulo a Git.

## Avances
- Semanas 1-2: propuesta y prototipos. Hecho.
- Semana 3: base (base de datos, login, roles). Hecho.
- Semanas 4-5: panel de administración. Hecho.
- Semanas 6-7: chat y base de conocimiento. Hecho.
- Semanas 8-9: integración con la IA. Hecho.
- Semana 10: control de tokens. Hecho.
- Semana 11: multi-idioma. Hecho.
- Semana 12: seguridad. Hecho.
- Semana 13: pruebas. Pendiente.
- Semana 14: documentación. Pendiente.
- Semana 15: entrega final. Pendiente.
