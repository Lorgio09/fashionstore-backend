from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
import jwt
from datetime import datetime, timedelta, timezone
import os
from dotenv import load_dotenv
from app.db.database import get_db 
from app.models.usuarios import Usuario 
from app.schemas.usuarios import UsuarioCreate, UsuarioResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

load_dotenv()
router = APIRouter()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = os.getenv("SECRET_KEY", "llave_de_respaldo")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7 # El token durará 7 días

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

@router.post("/registro", response_model=UsuarioResponse, status_code=status.HTTP_201_CREATED)
def registrar_usuario(usuario: UsuarioCreate, db: Session = Depends(get_db)):
    # Verificar si el correo ya está registrado
    usuario_existente = db.query(Usuario).filter(Usuario.email == usuario.email).first()
    if usuario_existente:
        raise HTTPException(
            status_code=400, 
            detail="El correo electrónico ya está registrado"
        )
    
    hashed_password = get_password_hash(usuario.password)
    
    nuevo_usuario = Usuario(
        nombre_completo=usuario.nombre_completo,
        email=usuario.email,
        password_hash=hashed_password,
        telefono=usuario.telefono,
        rol_id=usuario.rol_id,         
        sucursal_id=usuario.sucursal_id
    )

    db.add(nuevo_usuario)
    db.commit()
    db.refresh(nuevo_usuario)
    
    return nuevo_usuario

class UsuarioLogin(BaseModel):
    email: EmailStr
    password: str

@router.post("/login")
def login_usuario(usuario: UsuarioLogin, db: Session = Depends(get_db)):
    db_user = db.query(Usuario).filter(Usuario.email == usuario.email).first()
    
    if not db_user or not verify_password(usuario.password, db_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo o contraseña incorrectos"
        )
    
    access_token = create_access_token(
        data={"sub": db_user.email, "rol": db_user.rol_id, "nombre": db_user.nombre_completo}
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "usuario": {
            "id": db_user.id,
            "nombre": db_user.nombre_completo,
            "rol_id": db_user.rol_id
        }
    }
    
security = HTTPBearer()

def get_usuario_actual(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Token inválido")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="El token ha expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")
    
    usuario = db.query(Usuario).filter(Usuario.email == email).first()
    if usuario is None:
        raise HTTPException(status_code=401, detail="Usuario no encontrado")
    
    return usuario

@router.get("/perfil")
def obtener_perfil(usuario_actual: Usuario = Depends(get_usuario_actual)):
    # Si llegas aquí, el token es válido
    return {
        "mensaje": "¡Acceso autorizado a zona privada!",
        "datos_privados": {
            "nombre": usuario_actual.nombre_completo,
            "email": usuario_actual.email,
            "telefono": usuario_actual.telefono,
            "rol_id": usuario_actual.rol_id
        }
    }