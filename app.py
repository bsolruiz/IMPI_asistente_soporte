"""
IMPI - Asistente de soporte con IA para plataforma de calculo de bonos y comisiones.
Backend Flask + SQLite + JWT.

IMPORTANTE SOBRE LA IA:
  La llamada real a Claude esta controlada por la variable AI_ENABLED del .env.
  Por defecto AI_ENABLED=false  ->  el chat responde con un mensaje simulado y
  NO consume tokens de la API. Cuando quieras activarla, pon AI_ENABLED=true y
  coloca tu ANTHROPIC_API_KEY. Asi puedes probar toda la app sin gastar creditos.
"""

import os
import shutil
from datetime import datetime, timedelta

from sqlalchemy import text as sql_text

from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity, get_jwt
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

load_dotenv()

# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DOCS_DIR = os.path.join(BASE_DIR, "docs")
os.makedirs(DOCS_DIR, exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "instance"), exist_ok=True)

AI_ENABLED = os.getenv("AI_ENABLED", "false").lower() == "true"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-haiku-4-5"

# Nivel de respuesta -> tope de tokens de SALIDA por respuesta (max_tokens).
NIVELES = {"bajo": 512, "medio": 1024, "alto": 2048}
# Limite de tokens por defecto para un cliente nuevo (0 = sin limite).
LIMITE_TOKENS_DEFAULT = 100000

ALLOWED_EXTENSIONS = {".md", ".txt", ".xlsx", ".pdf"}
# Solo estas se leen como contexto de texto para Claude.
TEXT_CONTEXT_EXTENSIONS = {".md", ".txt", ".xlsx"}

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///impi.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", "dev-secret-change-me")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=12)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB por archivo

db = SQLAlchemy(app)
jwt = JWTManager(app)


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------
class Cliente(db.Model):
    __tablename__ = "cliente"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)  # hash
    rol = db.Column(db.String(20), nullable=False, default="cliente")  # 'admin' | 'cliente'
    activo = db.Column(db.Boolean, nullable=False, default=True)
    bases = db.Column(db.Integer, nullable=False, default=0)  # nro de bases de calculo
    # --- Control de consumo de tokens ---
    tokens_usados = db.Column(db.Integer, nullable=False, default=0)          # acumulado
    limite_tokens = db.Column(db.Integer, nullable=False, default=LIMITE_TOKENS_DEFAULT)  # 0 = sin limite
    nivel_respuesta = db.Column(db.String(10), nullable=False, default="medio")  # bajo|medio|alto
    # Fuerza al cliente a cambiar su contrasena temporal en el primer ingreso
    debe_cambiar_password = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    conversaciones = db.relationship(
        "Conversacion", backref="cliente", cascade="all, delete-orphan"
    )


class Conversacion(db.Model):
    __tablename__ = "conversacion"
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("cliente.id"), nullable=False)
    titulo = db.Column(db.String(80), nullable=False, default="Nueva consulta")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    mensajes = db.relationship(
        "Mensaje", backref="conversacion", cascade="all, delete-orphan",
        order_by="Mensaje.created_at"
    )


class Mensaje(db.Model):
    __tablename__ = "mensaje"
    id = db.Column(db.Integer, primary_key=True)
    conversacion_id = db.Column(db.Integer, db.ForeignKey("conversacion.id"), nullable=False)
    rol = db.Column(db.String(20), nullable=False)  # 'user' | 'assistant'
    contenido = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def cliente_docs_dir(cliente_id):
    path = os.path.join(DOCS_DIR, str(cliente_id))
    os.makedirs(path, exist_ok=True)
    return path


def ext_permitida(nombre):
    return os.path.splitext(nombre)[1].lower() in ALLOWED_EXTENSIONS


def estimar_tokens(texto):
    """Estimacion simple (~4 caracteres = 1 token). Se usa solo cuando la IA
    esta apagada, para que el contador funcione en modo prueba. Con la IA
    encendida se usa el conteo real que devuelve la API de Claude."""
    if not texto:
        return 0
    return max(1, len(texto) // 4)


def leer_xlsx_como_texto(path):
    """Lee un .xlsx y lo devuelve como texto plano, columnas separadas por |."""
    try:
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        lineas = []
        for ws in wb.worksheets:
            lineas.append(f"# Hoja: {ws.title}")
            for fila in ws.iter_rows(values_only=True):
                celdas = ["" if c is None else str(c) for c in fila]
                if any(celdas):
                    lineas.append(" | ".join(celdas))
        wb.close()
        return "\n".join(lineas)
    except Exception as e:
        return f"[No se pudo leer el xlsx: {e}]"


def construir_contexto(cliente_id):
    """Concatena TODOS los archivos de contexto del cliente en un solo string."""
    carpeta = cliente_docs_dir(cliente_id)
    partes = []
    for nombre in sorted(os.listdir(carpeta)):
        ruta = os.path.join(carpeta, nombre)
        if not os.path.isfile(ruta):
            continue
        ext = os.path.splitext(nombre)[1].lower()
        if ext not in TEXT_CONTEXT_EXTENSIONS:
            # .pdf u otros: no se leen como texto en esta version.
            continue
        if ext in (".md", ".txt"):
            try:
                with open(ruta, "r", encoding="utf-8", errors="ignore") as f:
                    contenido = f.read()
            except Exception as e:
                contenido = f"[No se pudo leer: {e}]"
        elif ext == ".xlsx":
            contenido = leer_xlsx_como_texto(ruta)
        else:
            continue
        partes.append(f"===== ARCHIVO: {nombre} =====\n{contenido}")
    return "\n\n".join(partes) if partes else "(Sin documentacion cargada.)"


# Plantillas del system prompt por idioma. El asistente responde en el idioma
# elegido por el cliente, pero se adapta si el cliente escribe en otro.
SYSTEM_PROMPTS = {
    "es": (
        "Eres un asistente de soporte especializado en la plataforma IMPI de "
        "calculo de bonos y comisiones para {nombre}. Responde en espanol de forma "
        "clara y concisa, salvo que el cliente escriba en otro idioma, en cuyo caso "
        "responde en el idioma del cliente. Si no tienes informacion suficiente, "
        "indicalo y sugiere contactar al administrador. DOCUMENTACION: {contexto}"
    ),
    "pt": (
        "Voce e um assistente de suporte especializado na plataforma IMPI de calculo "
        "de bonus e comissoes para {nombre}. Responda em portugues de forma clara e "
        "concisa, exceto se o cliente escrever em outro idioma, caso em que responda "
        "no idioma do cliente. Se nao tiver informacao suficiente, indique-o e sugira "
        "contatar o administrador. DOCUMENTACAO: {contexto}"
    ),
    "en": (
        "You are a support assistant specialized in the IMPI platform for bonus and "
        "commission calculation for {nombre}. Respond in English clearly and "
        "concisely, unless the client writes in another language, in which case "
        "respond in the client's language. If you lack sufficient information, say so "
        "and suggest contacting the administrator. DOCUMENTATION: {contexto}"
    ),
}

# Respuesta simulada (IA apagada) por idioma. NO consume tokens.
PLACEHOLDER_MSG = {
    "es": ("[MODO PRUEBA - IA desactivada]\n\n"
           "La integracion con Claude esta apagada (AI_ENABLED=false) para no "
           "consumir tokens. Cuando la actives, esta respuesta la generara el modelo "
           "con la documentacion de tu cuenta.\n\nTu pregunta fue: \"{q}\""),
    "pt": ("[MODO TESTE - IA desativada]\n\n"
           "A integracao com o Claude esta desligada (AI_ENABLED=false) para nao "
           "consumir tokens. Quando ativar, esta resposta sera gerada pelo modelo com "
           "a documentacao da sua conta.\n\nSua pergunta foi: \"{q}\""),
    "en": ("[TEST MODE - AI disabled]\n\n"
           "The Claude integration is off (AI_ENABLED=false) to avoid spending "
           "tokens. Once enabled, this response will be generated by the model using "
           "your account's documentation.\n\nYour question was: \"{q}\""),
}


def llamar_claude(nombre_cliente, contexto, historial, idioma="es", nivel="medio"):
    """
    Llama a Claude si AI_ENABLED=true. Si no, devuelve una respuesta simulada
    para poder probar la app sin consumir tokens.

    historial: lista de dicts {rol, contenido} (ya recortada a los ultimos 8).
    idioma: 'es' | 'pt' | 'en' (elegido por el cliente en el login).
    nivel: 'bajo' | 'medio' | 'alto' -> tope de tokens de la respuesta.

    Devuelve una tupla: (texto, tokens_entrada, tokens_salida).
    """
    if idioma not in SYSTEM_PROMPTS:
        idioma = "es"

    system_prompt = SYSTEM_PROMPTS[idioma].format(nombre=nombre_cliente, contexto=contexto)
    max_tokens = NIVELES.get(nivel, NIVELES["medio"])

    if not AI_ENABLED:
        ultima = historial[-1]["contenido"] if historial else ""
        texto = PLACEHOLDER_MSG[idioma].format(q=ultima)
        # Estimacion para que el contador funcione en modo prueba (sin consumo real).
        entrada = system_prompt + " ".join(m["contenido"] for m in historial)
        return texto, estimar_tokens(entrada), estimar_tokens(texto)

    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("sk-ant-aqui"):
        return ("[Error] AI_ENABLED=true pero falta una ANTHROPIC_API_KEY valida "
                "en el archivo .env.", 0, 0)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        mensajes = [{"role": m["rol"], "content": m["contenido"]} for m in historial]
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=mensajes,
        )
        texto = "".join(
            block.text for block in resp.content if getattr(block, "type", "") == "text"
        )
        # Conteo REAL que devuelve la API.
        t_in = getattr(resp.usage, "input_tokens", 0)
        t_out = getattr(resp.usage, "output_tokens", 0)
        return texto, t_in, t_out
    except Exception as e:
        return f"[Error al llamar a Claude: {e}]", 0, 0


def solo_admin():
    """Devuelve None si es admin, o una tupla (json, status) si no lo es."""
    claims = get_jwt()
    if claims.get("rol") != "admin":
        return jsonify({"error": "Acceso solo para administradores"}), 403
    return None


def cliente_actual():
    return db.session.get(Cliente, int(get_jwt_identity()))


# ---------------------------------------------------------------------------
# Vistas HTML
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("login.html")


@app.route("/admin")
def admin_page():
    return render_template("admin.html")


@app.route("/chat")
def chat_page():
    return render_template("chat.html")


@app.route("/cambiar-password")
def cambiar_password_page():
    return render_template("cambiar_password.html")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    cliente = Cliente.query.filter_by(email=email).first()
    if not cliente or not check_password_hash(cliente.password, password):
        return jsonify({"error": "Credenciales incorrectas"}), 401
    if not cliente.activo:
        return jsonify({"error": "Usuario desactivado. Contacta al administrador."}), 403

    token = create_access_token(
        identity=str(cliente.id),
        additional_claims={"rol": cliente.rol, "nombre": cliente.nombre},
    )
    return jsonify({
        "token": token, "rol": cliente.rol, "nombre": cliente.nombre,
        "debe_cambiar": cliente.debe_cambiar_password,
    })


@app.route("/api/cambiar-password", methods=["POST"])
@jwt_required()
def cambiar_password():
    c = cliente_actual()
    if not c:
        return jsonify({"error": "Cliente no valido"}), 401
    data = request.get_json(silent=True) or {}
    nueva = data.get("password") or ""
    if len(nueva) < 6:
        return jsonify({"error": "La contrasena debe tener al menos 6 caracteres"}), 400
    c.password = generate_password_hash(nueva)
    c.debe_cambiar_password = False
    db.session.commit()
    return jsonify({"mensaje": "Contrasena actualizada"})


# ---------------------------------------------------------------------------
# Admin - Clientes
# ---------------------------------------------------------------------------
@app.route("/api/admin/clientes", methods=["GET"])
@jwt_required()
def admin_listar_clientes():
    err = solo_admin()
    if err:
        return err
    clientes = Cliente.query.filter(Cliente.rol == "cliente").order_by(Cliente.nombre).all()
    salida = []
    for c in clientes:
        carpeta = cliente_docs_dir(c.id)
        n_docs = len([f for f in os.listdir(carpeta)
                      if os.path.isfile(os.path.join(carpeta, f))])
        n_consultas = Mensaje.query.join(Conversacion).filter(
            Conversacion.cliente_id == c.id, Mensaje.rol == "user"
        ).count()
        salida.append({
            "id": c.id, "nombre": c.nombre, "email": c.email,
            "activo": c.activo, "bases": c.bases,
            "docs": n_docs, "consultas": n_consultas,
            "tokens_usados": c.tokens_usados, "limite_tokens": c.limite_tokens,
            "nivel_respuesta": c.nivel_respuesta,
        })
    return jsonify(salida)


@app.route("/api/admin/clientes", methods=["POST"])
@jwt_required()
def admin_crear_cliente():
    err = solo_admin()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    nombre = (data.get("nombre") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    bases = int(data.get("bases") or 0)
    limite = int(data.get("limite_tokens", LIMITE_TOKENS_DEFAULT) or 0)
    nivel = data.get("nivel_respuesta") or "medio"
    if nivel not in NIVELES:
        nivel = "medio"

    if not nombre or not email or not password:
        return jsonify({"error": "nombre, email y password son obligatorios"}), 400
    if Cliente.query.filter_by(email=email).first():
        return jsonify({"error": "Ya existe un cliente con ese email"}), 409

    c = Cliente(
        nombre=nombre, email=email,
        password=generate_password_hash(password),
        rol="cliente", activo=True, bases=bases,
        limite_tokens=limite, nivel_respuesta=nivel,
        debe_cambiar_password=True,  # contrasena temporal: la cambia al primer ingreso
    )
    db.session.add(c)
    db.session.commit()
    cliente_docs_dir(c.id)  # crea su carpeta
    return jsonify({"id": c.id, "mensaje": "Cliente creado"}), 201


@app.route("/api/admin/clientes/<int:cid>", methods=["PUT"])
@jwt_required()
def admin_editar_cliente(cid):
    err = solo_admin()
    if err:
        return err
    c = db.session.get(Cliente, cid)
    if not c:
        return jsonify({"error": "Cliente no encontrado"}), 404

    data = request.get_json(silent=True) or {}
    if "nombre" in data and data["nombre"].strip():
        c.nombre = data["nombre"].strip()
    if "email" in data and data["email"].strip():
        nuevo = data["email"].strip().lower()
        existente = Cliente.query.filter_by(email=nuevo).first()
        if existente and existente.id != c.id:
            return jsonify({"error": "Ese email ya esta en uso"}), 409
        c.email = nuevo
    if "activo" in data:
        c.activo = bool(data["activo"])
    if "bases" in data and data["bases"] is not None:
        c.bases = int(data["bases"])
    if "limite_tokens" in data and data["limite_tokens"] is not None:
        c.limite_tokens = int(data["limite_tokens"])
    if "nivel_respuesta" in data and data["nivel_respuesta"] in NIVELES:
        c.nivel_respuesta = data["nivel_respuesta"]
    # password opcional: si viene vacio no se cambia
    if data.get("password"):
        c.password = generate_password_hash(data["password"])

    db.session.commit()
    return jsonify({"mensaje": "Cliente actualizado"})


@app.route("/api/admin/clientes/<int:cid>", methods=["DELETE"])
@jwt_required()
def admin_eliminar_cliente(cid):
    err = solo_admin()
    if err:
        return err
    c = db.session.get(Cliente, cid)
    if not c:
        return jsonify({"error": "Cliente no encontrado"}), 404
    if c.rol == "admin":
        return jsonify({"error": "No se puede eliminar un administrador"}), 400

    # Borra el cliente; sus conversaciones y mensajes se van en cascada.
    db.session.delete(c)
    db.session.commit()

    # Borra tambien su carpeta de documentos (docs/<id>/).
    carpeta = os.path.join(DOCS_DIR, str(cid))
    if os.path.isdir(carpeta):
        shutil.rmtree(carpeta, ignore_errors=True)

    return jsonify({"mensaje": "Cliente eliminado"})


@app.route("/api/admin/clientes/<int:cid>/reset-tokens", methods=["POST"])
@jwt_required()
def admin_reset_tokens(cid):
    """Reinicia a cero el contador de tokens de un cliente."""
    err = solo_admin()
    if err:
        return err
    c = db.session.get(Cliente, cid)
    if not c:
        return jsonify({"error": "Cliente no encontrado"}), 404
    c.tokens_usados = 0
    db.session.commit()
    return jsonify({"mensaje": "Contador reiniciado", "tokens_usados": 0})


# ---------------------------------------------------------------------------
# Admin - Documentos por cliente
# ---------------------------------------------------------------------------
@app.route("/api/admin/clientes/<int:cid>/docs", methods=["GET"])
@jwt_required()
def admin_listar_docs(cid):
    err = solo_admin()
    if err:
        return err
    if not db.session.get(Cliente, cid):
        return jsonify({"error": "Cliente no encontrado"}), 404
    carpeta = cliente_docs_dir(cid)
    archivos = []
    for nombre in sorted(os.listdir(carpeta)):
        ruta = os.path.join(carpeta, nombre)
        if os.path.isfile(ruta):
            archivos.append({"nombre": nombre, "tamano": os.path.getsize(ruta)})
    return jsonify(archivos)


@app.route("/api/admin/clientes/<int:cid>/docs", methods=["POST"])
@jwt_required()
def admin_subir_doc(cid):
    err = solo_admin()
    if err:
        return err
    if not db.session.get(Cliente, cid):
        return jsonify({"error": "Cliente no encontrado"}), 404
    if "archivo" not in request.files:
        return jsonify({"error": "No se envio ningun archivo (campo 'archivo')"}), 400
    f = request.files["archivo"]
    if not f.filename:
        return jsonify({"error": "Nombre de archivo vacio"}), 400
    if not ext_permitida(f.filename):
        return jsonify({"error": "Extension no permitida. Usa .md .txt .xlsx .pdf"}), 400

    nombre = secure_filename(f.filename)
    f.save(os.path.join(cliente_docs_dir(cid), nombre))
    return jsonify({"mensaje": "Archivo subido", "nombre": nombre}), 201


@app.route("/api/admin/clientes/<int:cid>/docs/<path:nombre>", methods=["DELETE"])
@jwt_required()
def admin_eliminar_doc(cid, nombre):
    err = solo_admin()
    if err:
        return err
    nombre = secure_filename(nombre)
    ruta = os.path.join(cliente_docs_dir(cid), nombre)
    if not os.path.isfile(ruta):
        return jsonify({"error": "Archivo no encontrado"}), 404
    os.remove(ruta)
    return jsonify({"mensaje": "Archivo eliminado"})


# ---------------------------------------------------------------------------
# Admin - Historial de conversaciones
# ---------------------------------------------------------------------------
@app.route("/api/admin/clientes/<int:cid>/historial", methods=["GET"])
@jwt_required()
def admin_historial_cliente(cid):
    err = solo_admin()
    if err:
        return err
    if not db.session.get(Cliente, cid):
        return jsonify({"error": "Cliente no encontrado"}), 404
    convs = Conversacion.query.filter_by(cliente_id=cid).order_by(
        Conversacion.created_at.desc()
    ).all()
    return jsonify([{
        "id": c.id, "titulo": c.titulo,
        "mensajes": len(c.mensajes),
        "fecha": c.created_at.isoformat(),
    } for c in convs])


@app.route("/api/admin/conversacion/<int:conv_id>", methods=["GET"])
@jwt_required()
def admin_ver_conversacion(conv_id):
    err = solo_admin()
    if err:
        return err
    conv = db.session.get(Conversacion, conv_id)
    if not conv:
        return jsonify({"error": "Conversacion no encontrada"}), 404
    return jsonify({
        "id": conv.id, "titulo": conv.titulo,
        "mensajes": [{
            "rol": m.rol, "contenido": m.contenido,
            "fecha": m.created_at.isoformat(),
        } for m in conv.mensajes],
    })


@app.route("/api/admin/conversacion/<int:conv_id>", methods=["DELETE"])
@jwt_required()
def admin_eliminar_conversacion(conv_id):
    """Elimina UNA conversacion (y sus mensajes, en cascada)."""
    err = solo_admin()
    if err:
        return err
    conv = db.session.get(Conversacion, conv_id)
    if not conv:
        return jsonify({"error": "Conversacion no encontrada"}), 404
    db.session.delete(conv)
    db.session.commit()
    return jsonify({"mensaje": "Conversacion eliminada"})


@app.route("/api/admin/clientes/<int:cid>/historial", methods=["DELETE"])
@jwt_required()
def admin_vaciar_historial(cid):
    """Elimina TODAS las conversaciones de un cliente (resetea su historial)."""
    err = solo_admin()
    if err:
        return err
    if not db.session.get(Cliente, cid):
        return jsonify({"error": "Cliente no encontrado"}), 404
    convs = Conversacion.query.filter_by(cliente_id=cid).all()
    n = len(convs)
    for conv in convs:
        db.session.delete(conv)
    db.session.commit()
    return jsonify({"mensaje": "Historial vaciado", "eliminadas": n})


# ---------------------------------------------------------------------------
# Chat (cliente)
# ---------------------------------------------------------------------------
@app.route("/api/chat/nueva", methods=["POST"])
@jwt_required()
def chat_nueva():
    c = cliente_actual()
    if not c:
        return jsonify({"error": "Cliente no valido"}), 401
    conv = Conversacion(cliente_id=c.id, titulo="Nueva consulta")
    db.session.add(conv)
    db.session.commit()
    return jsonify({"conversacion_id": conv.id}), 201


@app.route("/api/chat/historial", methods=["GET"])
@jwt_required()
def chat_historial():
    c = cliente_actual()
    if not c:
        return jsonify({"error": "Cliente no valido"}), 401
    convs = Conversacion.query.filter_by(cliente_id=c.id).order_by(
        Conversacion.created_at.desc()
    ).limit(20).all()
    return jsonify([{
        "id": conv.id, "titulo": conv.titulo,
        "mensajes": len(conv.mensajes),
        "fecha": conv.created_at.isoformat(),
    } for conv in convs])


@app.route("/api/chat/mensajes/<int:conv_id>", methods=["GET"])
@jwt_required()
def chat_mensajes(conv_id):
    c = cliente_actual()
    if not c:
        return jsonify({"error": "Cliente no valido"}), 401
    conv = db.session.get(Conversacion, conv_id)
    # AISLAMIENTO: la conversacion debe ser del cliente autenticado
    if not conv or conv.cliente_id != c.id:
        return jsonify({"error": "Conversacion no encontrada"}), 404
    return jsonify([{
        "rol": m.rol, "contenido": m.contenido,
        "fecha": m.created_at.isoformat(),
    } for m in conv.mensajes])


@app.route("/api/chat/mensaje", methods=["POST"])
@jwt_required()
def chat_mensaje():
    c = cliente_actual()
    if not c:
        return jsonify({"error": "Cliente no valido"}), 401

    data = request.get_json(silent=True) or {}
    conv_id = data.get("conversacion_id")
    pregunta = (data.get("pregunta") or "").strip()
    idioma = data.get("idioma") or "es"
    if not conv_id or not pregunta:
        return jsonify({"error": "conversacion_id y pregunta son obligatorios"}), 400

    # Si aun no cambio su contrasena temporal, no puede usar el chat.
    if c.debe_cambiar_password:
        return jsonify({"error": "debe_cambiar"}), 403

    conv = db.session.get(Conversacion, int(conv_id))
    # AISLAMIENTO
    if not conv or conv.cliente_id != c.id:
        return jsonify({"error": "Conversacion no encontrada"}), 404

    # LIMITE DE TOKENS: si el cliente ya alcanzo su tope, se bloquea.
    if c.limite_tokens and c.limite_tokens > 0 and c.tokens_usados >= c.limite_tokens:
        return jsonify({
            "error": "limite_tokens",
            "tokens_usados": c.tokens_usados,
            "limite_tokens": c.limite_tokens,
        }), 403

    # Guardar mensaje del usuario
    msg_user = Mensaje(conversacion_id=conv.id, rol="user", contenido=pregunta)
    db.session.add(msg_user)

    # Titulo con los primeros 80 chars del primer mensaje
    if conv.titulo == "Nueva consulta":
        conv.titulo = pregunta[:80]
    db.session.commit()

    # AHORRO DE TOKENS: solo los ultimos 8 mensajes
    ultimos = Mensaje.query.filter_by(conversacion_id=conv.id).order_by(
        Mensaje.created_at.desc()
    ).limit(8).all()
    historial = [{"rol": m.rol, "contenido": m.contenido} for m in reversed(ultimos)]

    contexto = construir_contexto(c.id)
    respuesta, t_in, t_out = llamar_claude(
        c.nombre, contexto, historial, idioma, c.nivel_respuesta
    )

    # Acumular consumo del cliente
    c.tokens_usados = (c.tokens_usados or 0) + t_in + t_out

    msg_bot = Mensaje(conversacion_id=conv.id, rol="assistant", contenido=respuesta)
    db.session.add(msg_bot)
    db.session.commit()

    return jsonify({
        "respuesta": respuesta,
        "conversacion_id": conv.id,
        "tokens_usados": c.tokens_usados,
        "limite_tokens": c.limite_tokens,
    })


# ---------------------------------------------------------------------------
# Inicializacion
# ---------------------------------------------------------------------------
def _migrar_columnas_tokens():
    """Agrega las columnas de tokens a una base de datos ya existente
    (SQLite) para no perder datos. Si la base es nueva, no hace nada."""
    with app.app_context():
        cols = [r[1] for r in db.session.execute(sql_text("PRAGMA table_info(cliente)")).fetchall()]
        if not cols:
            return  # tabla aun no existe; db.create_all() la creara completa
        alters = []
        if "tokens_usados" not in cols:
            alters.append("ALTER TABLE cliente ADD COLUMN tokens_usados INTEGER NOT NULL DEFAULT 0")
        if "limite_tokens" not in cols:
            alters.append(f"ALTER TABLE cliente ADD COLUMN limite_tokens INTEGER NOT NULL DEFAULT {LIMITE_TOKENS_DEFAULT}")
        if "nivel_respuesta" not in cols:
            alters.append("ALTER TABLE cliente ADD COLUMN nivel_respuesta VARCHAR(10) NOT NULL DEFAULT 'medio'")
        if "debe_cambiar_password" not in cols:
            alters.append("ALTER TABLE cliente ADD COLUMN debe_cambiar_password BOOLEAN NOT NULL DEFAULT 0")
        for a in alters:
            db.session.execute(sql_text(a))
        if alters:
            db.session.commit()
            print(f">> Migracion: agregadas {len(alters)} columna(s) de tokens.")


def init_db():
    with app.app_context():
        db.create_all()
        _migrar_columnas_tokens()
        # ADMIN POR DEFECTO
        if not Cliente.query.filter_by(email="admin@impi.com").first():
            admin = Cliente(
                nombre="Administrador",
                email="admin@impi.com",
                password=generate_password_hash("admin123"),
                rol="admin", activo=True, bases=0,
            )
            db.session.add(admin)
            db.session.commit()
            print(">> Usuario admin creado: admin@impi.com / admin123")


if __name__ == "__main__":
    init_db()
    estado_ia = "ACTIVADA" if AI_ENABLED else "DESACTIVADA (modo prueba, sin consumo)"
    print(f">> IMPI iniciando. IA: {estado_ia}")
    app.run(debug=True, port=5000)
