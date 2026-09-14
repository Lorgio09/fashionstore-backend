from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from app.db.database import SessionLocal
from app.models.usuarios import Usuario, Rol
from app.models.inventario import Sucursal
from app.schemas.usuarios import UsuarioCreate, UsuarioResponse, ClienteCreate

# ¡Aquí está la magia! Importamos la seguridad desde nuestro core
from app.core.security import get_password_hash, verify_password, create_access_token, get_usuario_actual

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Nota: Si prefieres, puedes mover esta clase a schemas/usuarios.py después
class UsuarioLogin(BaseModel):
    email: EmailStr
    password: str

# ==========================================
# 1. REGISTRO PÚBLICO (Para Clientes)
# ==========================================
@router.post("/registro/cliente", response_model=UsuarioResponse, status_code=status.HTTP_201_CREATED)
def registrar_cliente(cliente: ClienteCreate, db: Session = Depends(get_db)):
    # 1. Verificar si el correo ya existe
    if db.query(Usuario).filter(Usuario.email == cliente.email).first():
        raise HTTPException(status_code=400, detail="El correo ya está registrado")
    
    # 2. Buscar automáticamente el ID del rol "Cliente"
    rol_cliente = db.query(Rol).filter(Rol.nombre == "Cliente").first()
    if not rol_cliente:
        raise HTTPException(status_code=500, detail="Error interno: El rol 'Cliente' no existe en la base de datos")

    # 3. Crear el usuario inyectando los datos faltantes por debajo de la mesa
    nuevo_usuario = Usuario(
        nombre_completo=cliente.nombre_completo,
        email=cliente.email,
        password_hash=get_password_hash(cliente.password),
        telefono=None,             # El cliente lo puede llenar después en su perfil
        rol_id=rol_cliente.id,     # Asignación automática de rol
        sucursal_id=None           # Los clientes no pertenecen a una sucursal
    )

    db.add(nuevo_usuario)
    db.commit()
    db.refresh(nuevo_usuario)
    return nuevo_usuario

# ==========================================
# 2. REGISTRO INTERNO (Para Administradores)
# ==========================================
@router.post("/usuarios", response_model=UsuarioResponse, status_code=status.HTTP_201_CREATED)
def crear_empleado(usuario: UsuarioCreate, db: Session = Depends(get_db)):
    # Aquí podríamos agregar un Depends() para verificar que quien hace esto sea un Admin
    
    if db.query(Usuario).filter(Usuario.email == usuario.email).first():
        raise HTTPException(status_code=400, detail="El correo ya está registrado")
    
    nuevo_empleado = Usuario(
        nombre_completo=usuario.nombre_completo,
        email=usuario.email,
        password_hash=get_password_hash(usuario.password),
        telefono=usuario.telefono,
        rol_id=usuario.rol_id,        
        sucursal_id=usuario.sucursal_id
    )

    db.add(nuevo_empleado)
    db.commit()
    db.refresh(nuevo_empleado)
    return nuevo_empleado

@router.post("/login")
def login_usuario(usuario: UsuarioLogin, db: Session = Depends(get_db)):
    db_user = db.query(Usuario).filter(Usuario.email == usuario.email).first()
    
    # Aquí validamos usando la caja fuerte de security.py
    if not db_user or not verify_password(usuario.password, db_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo o contraseña incorrectos"
        )
    
    # Generamos la llave maestra (Token JWT)
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
    
# ==========================================
# 4. PERFIL (Ruta Protegida de Prueba)
# ==========================================
@router.get("/perfil")
def obtener_perfil(usuario_actual: Usuario = Depends(get_usuario_actual)):
    return {
        "mensaje": "¡Acceso autorizado a zona privada!",
        "datos_privados": {
            "nombre": usuario_actual.nombre_completo,
            "email": usuario_actual.email,
            "rol_id": usuario_actual.rol_id
        }
    }
    
@router.get("/roles")
def listar_roles(db: Session = Depends(get_db)):
    return db.query(Rol).all()

@router.get("/")
def listar_usuarios(db: Session = Depends(get_db)):
    # Devolvemos todos excepto las contraseñas, por supuesto
    return db.query(Usuario).all()

@router.get("/sembrar-datos")
def sembrar_datos(db: Session = Depends(get_db)):
    # 1. Crear la sucursal por defecto
    sucursal = Sucursal(nombre="Principal") 
    db.add(sucursal)
    
    # 2. Crear los 4 roles exactos de tu documentación
    rol1 = Rol(nombre="Cliente")
    rol2 = Rol(nombre="Administrador")
    rol3 = Rol(nombre="Encargado de sucursal")
    rol4 = Rol(nombre="Cajero")
    
    db.add_all([rol1, rol2, rol3, rol4])
    db.commit()
    
    return {"mensaje": "Los 4 roles y la sucursal fueron creados con éxito."}