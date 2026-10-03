# IMPI — Asistente de soporte con IA

Asistente de soporte para una plataforma de cálculo de bonos y comisiones.
Proyecto de prácticas universitarias. Flask + SQLite + JWT + Claude.

## Instalación

```bash
cd impi
python -m venv venv
# Windows:  venv\Scripts\activate
# Mac/Linux: source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Abre http://localhost:5000

## Usuario admin por defecto

Se crea automáticamente al arrancar la app por primera vez:

Desde `/admin` puedes crear clientes, subir su documentación y ver su historial.
Los clientes entran por la misma pantalla de login y van directo a `/chat`.

## La IA está APAGADA por defecto

Para no consumir tokens mientras pruebas, el `.env` trae `AI_ENABLED=false`.
En este modo el chat funciona igual pero devuelve una **respuesta simulada** en
lugar de llamar a Claude. Todo lo demás (login, clientes, documentos, historial,
aislamiento por cliente) funciona sin gastar créditos.


## Cómo funciona el contexto por cliente

Cada cliente tiene una carpeta `docs/<id>/`. Al preguntar, el backend lee TODOS
sus archivos (`.md`, `.txt`, `.xlsx`) y los concatena como contexto para Claude.
Los `.xlsx` se convierten a texto con columnas separadas por `|`. Los `.pdf` se
pueden subir y guardar, pero en esta versión no se leen como contexto de texto.

Para ahorrar tokens, en cada llamada solo se envían los **últimos 8 mensajes**
de la conversación. Un cliente nunca ve datos de otro: todo se filtra por el
`cliente_id` del JWT.

## Estructura

```
impi/
├── app.py            backend completo
├── .env              variables de entorno (IA apagada por defecto)
├── requirements.txt
├── docs/             archivos de contexto por cliente (docs/1/, docs/2/, ...)
├── instance/         impi.db (SQLite, se crea solo)
├── templates/        login.html, admin.html, chat.html
└── static/css/base.css
```
