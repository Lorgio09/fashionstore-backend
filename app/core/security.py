import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.auditoria import Bitacora
from app.models.usuarios import Usuario

# ==========================================
# 1. CONFIGURACIÓN BÁSICA
# ==========================================
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = os.getenv("SECRET_KEY", "llave_de_respaldo")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # El token durará 7 días

security = HTTPBearer()
security_opcional = HTTPBearer(auto_error=False)


# ==========================================
# 2. FUNCIONES DE ENCRIPTACIÓN
# ==========================================
def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# ==========================================
# 3. GENERACIÓN DE TOKENS
# ==========================================
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def _usuario_desde_token(token: str, db: Session) -> Usuario:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="El token ha expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")

    email = payload.get("sub")
    if email is None:
        raise HTTPException(status_code=401, detail="Token inválido")

    # La empresa del usuario se toma SIEMPRE de la base de datos, no del token ni de la petición.
    usuario = (
        db.query(Usuario)
        .execution_options(sin_tenant=True)
        .filter(Usuario.email == email)
        .first()
    )
    if usuario is None:
        raise HTTPException(status_code=401, detail="Usuario no encontrado")
    if not usuario.activo:
        raise HTTPException(status_code=401, detail="El usuario está desactivado")
    return usuario


# ==========================================
# 4. GUARDIAS DE SEGURIDAD (Dependencias)
# ==========================================
def get_usuario_actual(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> Usuario:
    return _usuario_desde_token(credentials.credentials, db)


def get_usuario_opcional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_opcional),
    db: Session = Depends(get_db),
) -> Optional[Usuario]:
    """Para rutas públicas: si viene un token válido se usa, si no se continúa como anónimo."""
    if credentials is None:
        return None
    try:
        return _usuario_desde_token(credentials.credentials, db)
    except HTTPException:
        return None


def registrar_bitacora(db: Session, usuario_id: int, accion: str, tabla: str, registro_id: int, detalle: str = ""):
    """Registra el movimiento en la bitácora (la empresa se asigna automáticamente)."""
    nuevo_registro = Bitacora(
        accion=accion,
        tabla_afectada=tabla,
        registro_id=registro_id,
        detalle=detalle[:255] if detalle else detalle,
        usuario_id=usuario_id,
    )
    db.add(nuevo_registro)
    db.commit()
