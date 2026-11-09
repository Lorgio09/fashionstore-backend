# Contrato API — FashionStore SaaS (parcial 2)

Versión 5.4 · 2026-11-09 · Fuente única para la PWA (Angular) y la app móvil (Flutter).
Cambios v5.4: **cara pública de la plataforma** (§2.1): directorio de tiendas y planes sin token, para que la web y la app muestren FashionStore como proveedor y cada tienda con su propio nombre.
Cambios v5.3: **cambio de prenda sin conexión (CU-19)**: operación `CAMBIO` en `/sync/operaciones` (§6.5); `/sync/catalogo` trae `politica_devoluciones` y `ventas_recientes` para el personal (§6.1); conflictos de un cambio (§6.4).
Cambios v5.2: reservas con nombre de prenda, talla, color, precio y sucursal (§3.1); `POST /usuarios/registro/cliente` responde **409** si el correo ya existe.
Cambios v5.1: backend nuevo desplegado en Render (§1).
Cambios v5: devoluciones y cambios, notas de crédito y caja (§9); nota de crédito como pago en `/catalogo/checkout/presencial`; reporte IA `devoluciones_por_motivo`.
Cambios v4: módulo de analítica con Machine Learning y dashboard (§8); 3 reportes inteligentes nuevos en §7.1.
Cambios v3: reportes generativos con IA (§7) y empresa demo "Estilo Urbano" con 6 meses de ventas (§1).
Cambios v2: sincronización offline (§6) implementada y probada; nuevo estado `ERROR`, `fecha_visita` en hora local y formato de conflictos y registro.
Si algo de este contrato no alcanza, **no inventes el endpoint**: anótalo y pídelo al backend.

Leyenda: ✅ implementado y probado · 🛠 en construcción (se avisará cuando esté listo)

---

## 1. Entorno de desarrollo

| | URL |
|---|---|
| Backend local | `http://127.0.0.1:8000/api` (Swagger: `http://127.0.0.1:8000/docs`) |
| Desde emulador Android | `http://10.0.2.2:8000/api` |
| Desde celular físico | `http://<IP-LAN-de-la-PC>:8000/api` (levantar uvicorn con `--host 0.0.0.0`) |
| Producción (Render) | `https://fashionstore-api-kedu.onrender.com/api` — **versión nueva desplegada el 2026-11-04** (misma base de datos demo que la local). El plan gratuito se duerme: la primera petición puede tardar ~1 min |

Levantar el backend (carpeta `fashionstore-backend`): `venv\Scripts\python -m uvicorn main:app --reload`
CORS permite `http://localhost:4200` y `http://127.0.0.1:4200`.

Usuarios demo (contraseña `FashionStore2026!`):

| Email | Rol | Empresa (slug) | Plan |
|---|---|---|---|
| `plataforma@fashionstore.com` | Administrador de plataforma | — | — |
| `admin@modaandina.com` | Administrador | `moda-andina` | Básico |
| `cajero@modaandina.com` | Cajero (con sucursal asignada) | `moda-andina` | Básico |
| `cliente@modaandina.com` | Cliente | `moda-andina` | Básico |
| `admin@estilourbano.com` | Administrador | `estilo-urbano` | Profesional |
| `encargado@estilourbano.com` | Encargado (sucursal Equipetrol) | `estilo-urbano` | Profesional |
| `cajero@estilourbano.com` | Cajero (sucursal Centro) | `estilo-urbano` | Profesional |
| `cliente@estilourbano.com` | Cliente | `estilo-urbano` | Profesional |
| (usuarios existentes del parcial 1) | los de siempre | `fashionstore` | Profesional |

**Estilo Urbano es la empresa para demostrar reportes IA y ML**:
- 3 sucursales (Equipetrol, Centro y Norte) y tienda en línea.
- 14 prendas en 6 categorías y 50 clientes.
- Unas 3.500 ventas sintéticas, desde 6 meses atrás hasta el día anterior a ejecutar la semilla.

Para cargarla, ejecuta `venv\Scripts\python -m scripts.seed_demo`.

---

## 2. Multitenancy ✅

- Cada **empresa** contratante es un tenant. Todo dato de negocio pertenece a una empresa.
- **Usuario autenticado:** la empresa se toma del usuario en el servidor. El cliente NO envía `empresa_id` para elegir empresa.
- **Visitante anónimo (tienda pública):** enviar el header `X-Empresa: <slug>` (ej. `moda-andina`). Sin header se usa la tienda por defecto del servidor (`estilo-urbano` en Render). Si hay token, el token manda y el header se ignora.
- Un recurso de otra empresa responde **404** (no se revela que existe).

### 2.1 Cara pública de la plataforma ✅ (sin token)

**Dos marcas:** *FashionStore* es la plataforma (el proveedor del servicio). Cada empresa es una **tienda con su propio nombre**. En la tienda y en el panel de la empresa se muestra el nombre de la empresa, no "FashionStore". FashionStore aparece en la portada, en el panel de plataforma y como "con tecnología de FashionStore" al pie.

| Método | Ruta | Respuesta |
|---|---|---|
| GET | `/publico/tiendas` | Tiendas **activas** con al menos una sucursal activa (las suspendidas o sin sucursales no aparecen), por nombre |
| GET | `/publico/tiendas/{slug}` | Una tienda con sus sucursales. **404** si no existe o está suspendida |
| GET | `/publico/planes` | Planes vigentes para la página de precios, del más barato al más caro |

```json
// GET /publico/tiendas  → lista de:
{ "slug": "estilo-urbano", "nombre": "Estilo Urbano S.R.L.", "sucursales": 3, "prendas": 14,
  "categorias": ["Accesorios", "Calzados", "Camisas", "Chamarras", "Pantalones", "Poleras"],  // máx. 6
  "portada_url": null }        // imagen de una prenda si hay; si es null, usar un fondo con la inicial

// GET /publico/tiendas/estilo-urbano → lo mismo más:
{ "correo": "...", "telefono": "...",
  "lista_sucursales": [ { "id": 1, "nombre": "Equipetrol", "direccion": "..." } ] }

// GET /publico/planes → lista de:
{ "codigo": "PROFESIONAL", "nombre": "Profesional", "precio_mensual": 450.0, "max_sucursales": 10,
  "max_usuarios": null,        // null = sin límite
  "permite_offline": true, "permite_reportes_ia": true }
```
Después de elegir la tienda, el catálogo se pide como siempre con `X-Empresa: <slug>`. Con sesión iniciada, el nombre de la empresa del usuario viene en el login (`empresa.razon_social`) y en `/empresa/mi-empresa`.

### Login `POST /usuarios/login`
```json
// request
{ "email": "cajero@modaandina.com", "password": "FashionStore2026!" }
// response 200
{
  "access_token": "eyJ...", "token_type": "bearer",
  "usuario": { "id": 7, "nombre": "Cajero Moda Andina", "rol_id": 3, "rol_nombre": "Cajero", "sucursal_id": 2 },
  "empresa": { "id": "uuid", "razon_social": "Moda Andina S.R.L.", "slug": "moda-andina" }   // null para el admin de plataforma
}
```
Payload del JWT: `sub` (email), `id`, `rol` (= rol_id), `rol_nombre`, `nombre`, `empresa_id`, `sucursal_id`, `exp`.

> ⚠️ **Usar `rol_nombre`, nunca `rol_id`, para permisos en el cliente.** Los ids de rol difieren entre la base local y la de Render.
> Nombres exactos: `Cliente`, `Administrador`, `Encargado de sucursal`, `Cajero`, `Administrador de plataforma`.

Errores de login: 401 credenciales/usuario desactivado · 403 empresa suspendida.

### Mi empresa `GET /empresa/mi-empresa` (cualquier usuario de una empresa)
```json
{
  "empresa": { "id": "uuid", "razon_social": "...", "nit": "...", "slug": "moda-andina", "estado": "ACTIVA", ... },
  "suscripcion": {
    "estado": "ACTIVA",              // ACTIVA | VENCIDA | SUSPENDIDA | PROGRAMADA | SIN_SUSCRIPCION
    "plan": { "id": 1, "codigo": "BASICO", "nombre": "Básico", "max_sucursales": 2, "max_usuarios": null },
    "periodicidad": "ANUAL", "fecha_inicio": "2026-11-03", "fecha_fin": "2027-11-03", "dias_restantes": 365,
    "uso": { "sucursales_activas": 1, "usuarios_internos": 2 },
    "funciones": { "reportes_ia": false, "offline": true }
  }
}
```
Usar `funciones` para mostrar/ocultar opciones (ej. menú de reportes IA). El backend igual lo valida.

---

## 3. Cambios en endpoints existentes ✅

| Endpoint | Ahora |
|---|---|
| `GET /catalogo/`, `/catalogo/{id}`, `/catalogo/{id}/variantes`, `/catalogo/categorias`, `/catalogo/colecciones`, `/catalogo/temporadas`, `/catalogo/agrupado/secciones`, `/catalogo/sucursales` | Públicos por tienda (`X-Empresa` o token). `/catalogo/sucursales` devuelve solo **activas** e incluye `activa` |
| `POST /catalogo/checkout`, `/catalogo/checkout/stripe`, `/checkout/{id}/simular-pago`, `/simular-rechazo`, `/catalogo/sucursales-disponibles`, `POST /usuarios/registro/cliente` | Públicos por tienda (`X-Empresa` o token) |
| `GET /catalogo/proveedores` | **Requiere token** (Administrador o Encargado) |
| `POST /catalogo/`, `PUT/DELETE /catalogo/{id}`, `POST categorias/proveedores/colecciones/temporadas/variantes-stock` | Administrador o Encargado |
| `POST /catalogo/sucursales` | Solo Administrador. **409** si supera el límite del plan |
| `POST /catalogo/checkout/presencial`, `GET /catalogo/inventario/sucursal/{id}`, `/catalogo/ordenes/historial`, `/catalogo/dashboard/resumen` | Personal (Administrador, Encargado, Cajero). Cajero/Encargado solo venden en su sucursal |
| `POST /reservas/` | **Requiere token.** Cuerpo y respuesta en §3.1 |
| `GET /reservas/sucursal/{id}`, `PUT /reservas/{id}/estado` | Personal |
| `GET /reservas/cliente/{id}` | Token; un Cliente solo ve las suyas. Mismo formato que la respuesta de §3.1 (lista) |
| `POST /usuarios/registro/cliente`, `POST /usuarios/usuarios` | **409** "El correo ya está registrado" si el correo existe (en cualquier empresa) |
| `GET /usuarios/`, `POST /usuarios/usuarios` | Solo Administrador. Ya no devuelve `password_hash` |
| `GET /auditoria/` | Solo Administrador |
| `POST /ia/generar-reporte` | Administrador/Encargado **y plan Profesional** (403 con plan Básico) |
| Eliminados | `/usuarios/sembrar-datos`, `/catalogo/parche-db`, `/catalogo/migrar-tablas-ordenes`, `/parche-db` |

Las órdenes ahora traen `canal` (`WEB`/`PRESENCIAL`/`OFFLINE`), `metodo_pago`, `sucursal_id`, `usuario_id`, `cliente_id`, `uuid_operacion`.

### 3.1 Reservas ✅

`POST /reservas/` — cuerpo:
```json
{
  "sucursal_id": 1,
  "fecha_visita": "2026-11-10T10:00:00",   // hora local de la tienda, sin zona
  "cliente_id": 5,                          // solo si reserva el personal; si es Cliente se ignora y se usa su id
  "detalles": [{"variante_id": 12, "cantidad": 1}]
}
```
- El stock de la sucursal se descuenta al reservar y se devuelve si la reserva pasa a `Cancelada`.
- Errores: 400 stock insuficiente · 404 sucursal/variante/cliente inexistente o de otra empresa · 409 sucursal inactiva · 422 cantidad ≤ 0 o falta `cliente_id` (personal).

Respuesta (igual en `POST /reservas/`, `GET /reservas/cliente/{id}` y `GET /reservas/sucursal/{id}`, estas dos como lista):
```json
{
  "id": 31, "estado": "Pendiente",          // Pendiente | Preparada | Completada | Cancelada
  "fecha_creacion": "2026-11-08T14:02:11", "fecha_visita": "2026-11-10T10:00:00",
  "sucursal_id": 1, "sucursal_nombre": "Equipetrol",
  "cliente_id": 5, "usuario_id": null,      // usuario_id = empleado que la registró (null si la hizo el cliente)
  "detalles": [{"id": 40, "variante_id": 12, "cantidad": 1, "prenda_id": 3,
                "prenda_nombre": "Chaqueta Denim", "talla": "M", "color": "Azul", "precio": 349.0}]
}
```
`precio` es el precio base actual de la prenda (la reserva no congela precio; se cobra al retirar).

---

## 4. Endpoints nuevos SaaS ✅

### Administrador de empresa — `/empresa`
| Método | Ruta | Uso |
|---|---|---|
| GET | `/empresa/mi-empresa` | Plan, estado, uso y funciones (ver arriba) |
| GET | `/empresa/sucursales` | Todas las sucursales (activas e inactivas) |
| POST | `/empresa/sucursales` | `{nombre, direccion?}` · 409 si supera el límite |
| PATCH | `/empresa/sucursales/{id}/estado` | `{activa: true/false}` · 409 al activar sobre el límite |

### Administrador de plataforma — `/plataforma`
| Método | Ruta | Body / uso |
|---|---|---|
| GET | `/plataforma/planes` | Lista de planes |
| POST | `/plataforma/planes` | `{codigo, nombre, precio_mensual, max_sucursales, max_usuarios?, permite_offline, permite_reportes_ia, activo}` |
| PUT | `/plataforma/planes/{id}` | Igual que POST |
| GET | `/plataforma/empresas` | Empresas + `suscripcion` (mismo formato que mi-empresa) |
| POST | `/plataforma/empresas` | `{razon_social, nit, slug, correo?, telefono?, plan_codigo, periodicidad: MENSUAL/ANUAL, admin_nombre, admin_email, admin_password}` · 409 NIT/slug/email duplicado |
| GET | `/plataforma/empresas/{id}` | Datos de la empresa |
| PATCH | `/plataforma/empresas/{id}/estado` | `{estado: ACTIVA/SUSPENDIDA}` |
| GET | `/plataforma/empresas/{id}/suscripcion` | Resumen de suscripción |
| GET | `/plataforma/empresas/{id}/suscripciones` | Historial |
| POST | `/plataforma/empresas/{id}/suscripcion` | Asignar/cambiar plan `{plan_codigo, periodicidad, fecha_inicio?}` · 409 si el downgrade supera el límite |
| POST | `/plataforma/empresas/{id}/suscripcion/renovar` | Renovación simulada |
| PATCH | `/plataforma/empresas/{id}/suscripcion/estado` | `{estado: ACTIVA/SUSPENDIDA}` |

---

## 5. Errores

Siempre `{"detail": "mensaje en español"}` (o lista de validación en 422). Mostrar `detail` al usuario.

| Código | Significado |
|---|---|
| 401 | Sin token / token vencido → volver al login |
| 403 | Rol sin permiso, plan no incluye la función, empresa suspendida, o **suscripción vencida (solo lectura)** |
| 404 | No existe **o pertenece a otra empresa** |
| 409 | Límite del plan, duplicado, o conflicto de estado |
| 422 | Datos inválidos |

---

## 6. Sincronización offline ✅

Requisitos para usar `/sync`:
- El plan tiene que incluir offline (los dos planes lo incluyen).
- La suscripción tiene que estar vigente. Si está suspendida o vencida, `/sync/catalogo` y `/sync/operaciones` responden **403**. El dispositivo conserva todo en `LOCAL` y reintenta después.

Reglas comunes (PWA = IndexedDB, Flutter = SQLite):

1. Toda operación offline lleva un **`uuid` v4 generado en el dispositivo**. Es la clave de idempotencia: reenviarla nunca duplica (RNF05).
2. Estados locales: `LOCAL` → `ENVIADA` → `CONFIRMADA` | `RECHAZADA` | `CONFLICTO`.
   - Si el envío falla (sin red, timeout, 5xx), vuelve a `LOCAL` con `intentos + 1` y `ultimo_error`.
   - Si una operación vuelve con `"estado": "ERROR"` (falla temporal del servidor solo en esa operación), también vuelve a `LOCAL` y se reintenta. No es un estado final.
   - Una operación en `ENVIADA` al reabrir la app se trata como `LOCAL` y se reenvía (es seguro).
   - **Nunca se borra una operación** por haberla intentado enviar (RN18). Las finales se conservan como historial.
3. Se sincroniza: con botón manual, al volver la conexión (evento online) y cada 60 s mientras haya red.
4. Solo se envían las operaciones del **usuario logueado** (`usuario_id` = el del token).
5. Al registrar una venta/reserva offline, descontar el **stock local conocido** para que las siguientes operaciones lo vean; la pantalla debe indicar que es stock estimado.
6. HTTP 401 o 403 en el lote → no cambiar estados; mostrar el mensaje (ej. suscripción vencida) y reintentar después.

Campos mínimos de cada operación local: `uuid, tipo, empresa_id, sucursal_id, usuario_id, creado_en, estado, intentos, ultimo_intento, ultimo_error, servidor_id, mensaje_servidor` + los datos de la venta/reserva con sus ítems (variante, nombre/talla/color para mostrar, cantidad, precio unitario usado, total, forma de pago, cliente si corresponde).

### 6.1 Preparar dispositivo — `GET /sync/catalogo?sucursal_id={opcional}`
Cualquier usuario de la empresa. Cajero/Encargado reciben solo su sucursal; Administrador y Cliente, todas las activas.
```json
{
  "generado_en": "2026-11-03T19:20:00Z",
  "vigencia_horas": 24,
  "empresa": { "id": "uuid", "razon_social": "...", "slug": "moda-andina" },
  "usuario": { "id": 7, "nombre": "...", "rol_nombre": "Cajero", "sucursal_id": 2 },
  "sucursales": [ { "id": 2, "nombre": "Moda Andina - Centro", "direccion": "..." } ],
  "categorias": [ { "id": 1, "nombre": "Poleras" } ],
  "prendas": [
    { "id": 3, "nombre": "Polera Andina Algodón", "descripcion": "...", "precio_base": 89.0, "imagen_url": null,
      "categoria_id": 1, "variantes": [ { "id": 10, "talla": "M", "color": "Blanco", "codigo_sku": "MA-3-M-BLA" } ] }
  ],
  "inventario": [ { "variante_id": 10, "sucursal_id": 2, "stock_disponible": 15 } ],
  "clientes": [ { "id": 9, "nombre_completo": "...", "email": "...", "telefono": null } ],  // solo para personal
  // --- solo para personal (Cajero, Encargado, Administrador): para cambios sin conexión (§6.5) ---
  "politica_devoluciones": { "plazo_cambio_dias": 30, "plazo_garantia_dias": 90, "categorias_no_retornables": [4],
                             "max_cambios_por_prenda": 2, "fuera_de_plazo": "RECHAZAR", "recargo_pct": 0.0 },
  "ventas_recientes": [   // ventas pagadas de esas sucursales dentro del plazo de cambio, la más nueva primero (máx. 300)
    { "orden_id": 154, "uuid_operacion": "6f1c2a9e-...",   // uuid_operacion: si fue una venta offline (null si no)
      "fecha": "2026-11-03T18:05:00Z", "canal": "OFFLINE", "sucursal_id": 2, "cliente_id": null,
      "nombre_cliente": "Cliente ocasional", "total": 178.0,
      "items": [ { "detalle_orden_id": 301, "prenda_id": 3, "prenda": "Polera Andina Algodón", "variante_id": 10,
                   "talla": "M", "color": "Blanco", "cantidad": 2, "precio_unitario": 89.0,
                   "devuelto": 0, "cambios_realizados": 0, "retornable": true } ] }
  ]
}
```
Guardar todo con `generado_en`. Mostrar siempre "Datos al <fecha>"; marcar **desactualizado** si pasaron más de `vigencia_horas` o si se está offline.

### 6.2 Enviar operaciones — `POST /sync/operaciones`
Máximo 50 operaciones por lote, ordenadas por `creado_en`.
```json
{
  "dispositivo_id": "uuid-del-dispositivo",
  "operaciones": [
    {
      "uuid": "6f1c2a9e-...", "tipo": "VENTA",
      "empresa_id": "uuid", "sucursal_id": 2, "usuario_id": 7,
      "creado_en": "2026-11-03T14:05:00-04:00",
      "datos": {
        "metodo_pago": "EFECTIVO",
        "cliente_id": null, "nombre_cliente": "Cliente ocasional",
        "total": 178.0,
        "items": [ { "variante_id": 10, "cantidad": 2, "precio_unitario": 89.0 } ]
      }
    },
    {
      "uuid": "a2b9...", "tipo": "RESERVA",
      "empresa_id": "uuid", "sucursal_id": 2, "usuario_id": 7,
      "creado_en": "2026-11-03T14:10:00-04:00",
      "datos": {
        "cliente_id": 9,                       // si el usuario es Cliente se ignora y se usa el suyo
        "fecha_visita": "2026-11-05T10:00:00", // hora local de la tienda, sin zona (igual que POST /reservas)
        "items": [ { "variante_id": 10, "cantidad": 1 } ]
      }
    }
  ]
}
```
Respuesta **200** con un resultado por operación (en el mismo orden):
```json
{
  "procesadas": 2,
  "resultados": [
    { "uuid": "6f1c2a9e-...", "estado": "CONFIRMADA", "servidor_id": 154, "duplicada": false,
      "mensaje": "Venta registrada" },
    { "uuid": "a2b9...", "estado": "CONFLICTO", "servidor_id": null, "duplicada": false,
      "mensaje": "Stock insuficiente en la sucursal",
      "detalle": { "items": [ { "variante_id": 10, "solicitado": 1, "disponible": 0 } ] } }
  ]
}
```
Reglas del servidor:
- `CONFIRMADA`: se creó la venta/reserva y se descontó el stock de esa sucursal en la misma transacción (RNF04). `servidor_id` = id de la orden o reserva.
- `CONFLICTO`: el stock central no alcanza; **no se descuenta nada** y el inventario nunca queda negativo (RN21). Lo resuelve un Encargado/Administrador en la web (6.4).
- `RECHAZADA` (final). Motivos:
  - la empresa no es la del token;
  - el `usuario_id` no es el del token;
  - la sucursal no existe, está inactiva o es de otra empresa;
  - un Cajero o Encargado opera fuera de su sucursal asignada;
  - una variante es de otra empresa;
  - alguna cantidad es ≤ 0;
  - la forma de pago no es `EFECTIVO`;
  - el total no coincide con la suma de los ítems (tolerancia de 0.01);
  - un Cliente envía una `VENTA`;
  - el personal envía una `RESERVA` sin `cliente_id` válido;
  - el tipo es desconocido o faltan datos (en ese caso `detalle.errores` dice qué falta).
- `ERROR` (no final): falla temporal del servidor. No se guardó nada; reenviarla más tarde.
- Reenviar un `uuid` ya procesado devuelve **el mismo resultado** con `"duplicada": true` y no crea nada nuevo (RNF05). Lo mismo pasa si el uuid se repite dentro del mismo lote.
- Cada operación se procesa en su propia transacción: un conflicto no afecta a las demás del lote.
- La venta queda con `canal: "OFFLINE"` y `fecha_orden = creado_en` (la hora real de la venta). La reserva queda en estado `Pendiente`.
- Un lote de más de 50 operaciones o con la cabecera mal formada (`uuid` no válido, falta `sucursal_id`…) responde **422** completo: es un error del cliente y no se procesa nada.

### 6.3 Consultar estado — `POST /sync/estado`
- **Petición:** `{"uuids": ["...", "..."]}`, con un máximo de 200.
- **Respuesta:** `{"resultados": [ ...mismo formato... ]}`.
- Si el servidor nunca recibió un uuid, responde `"estado": "DESCONOCIDA"`: hay que reenviarlo.
- Cajero y Cliente solo ven sus propias operaciones; Encargado y Administrador ven las de toda la empresa.
- Úsalo para refrescar las operaciones en `CONFLICTO`, porque pueden haberse resuelto en la web.

### 6.4 Conflictos (solo web, Encargado y Administrador)
| Método | Ruta | Uso |
|---|---|---|
| GET | `/sync/conflictos?sucursal_id=` | Operaciones en CONFLICTO. El Encargado solo ve las de su sucursal |
| POST | `/sync/conflictos/{uuid}/resolver` | Resuelve el conflicto. Devuelve un resultado con el formato de 6.2 |
| GET | `/sync/registro?estado=&desde=&limite=200` | Bitácora de sincronización de la empresa (diagnóstico, RNF10). Solo Administrador |

Cada elemento de `GET /sync/conflictos`:
```json
{
  "uuid": "...", "tipo": "VENTA", "estado": "CONFLICTO",
  "sucursal": { "id": 2, "nombre": "Moda Andina - Centro" },
  "usuario": { "id": 7, "nombre": "Cajero Moda Andina" },
  "creado_en": "2026-11-03T18:05:00Z", "recibido_en": "2026-11-03T19:30:00Z",
  "mensaje": "Stock insuficiente en la sucursal",
  "datos": { "metodo_pago": "EFECTIVO", "total": 178.0, "nombre_cliente": "...", "cliente_id": null },
  "items": [ { "variante_id": 10, "prenda": "Polera Andina", "talla": "M", "color": "Blanco",
               "cantidad": 2, "precio_unitario": 89.0, "stock_actual": 1 } ]
}
```

Cómo se resuelve:
- **Rechazar.** Se envía `{"accion": "RECHAZAR", "motivo": "Se devolvió el dinero"}`; el motivo es obligatorio. La operación queda `RECHAZADA` con el mensaje "Rechazada por <nombre>: <motivo>".
- **Ajustar.** Se envía `{"accion": "AJUSTAR", "items": [{"variante_id": 10, "cantidad": 1}]}`.
  - Solo se permiten variantes de la operación original y cantidades iguales o menores a las originales. Si un ítem no se incluye, se quita.
  - En las ventas se conserva el precio unitario original y el total se recalcula.
  - La operación queda `CONFIRMADA` y el responsable sigue siendo quien la registró.
  - Si el stock todavía no alcanza, responde **409** y no se cambia nada. Para reintentar después de reponer stock, se envían las mismas cantidades.
- **Conflicto de un `CAMBIO`.** Los `items` del conflicto son las prendas **a entregar** (`entregados`) y `datos` trae el resto (`orden_id`, `motivo`, `devueltos`, `diferencia`…). No se ajustan cantidades:
  - `RECHAZAR` igual que arriba (el Encargado resuelve con el cliente en tienda);
  - `{"accion": "AJUSTAR"}` **sin `items`** reintenta el cambio tal cual (después de reponer stock). Si todavía no alcanza, **409**.
- Si la operación ya no está en conflicto, responde **409**. Si es de otra empresa, responde **404**.

### 6.5 Cambio de prenda sin conexión (CU-19) ✅ — tipo `CAMBIO`

Solo personal (un Cliente recibe `RECHAZADA`). El cajero inspecciona la prenda en el momento, entrega la nueva y, si el cliente paga una diferencia, la cobra **en efectivo**. Va en el mismo lote de `POST /sync/operaciones`, con el mismo uuid, estados e idempotencia.
```json
{
  "uuid": "c0ffee...", "tipo": "CAMBIO", "empresa_id": "uuid", "sucursal_id": 2, "usuario_id": 7,
  "creado_en": "2026-11-05T11:20:00-04:00",
  "datos": {
    "orden_id": 154,             // venta original ya sincronizada…
    "venta_uuid": null,          // …o el uuid de la VENTA offline si todavía no tiene orden_id (solo uno de los dos)
    "motivo": "TALLA",           // TALLA | AJUSTE_MEDIDA | COLOR | DEFECTO | PRODUCTO_EQUIVOCADO | YA_NO_LO_DESEA
    "inspeccion": "APTA",        // APTA (por defecto) | NO_APTA (solo con motivo DEFECTO)
    "devueltos":  [ { "detalle_orden_id": 301, "cantidad": 1 } ],   // o { "variante_id": 10, "cantidad": 1 } si no se conoce la línea
    "entregados": [ { "variante_id": 11, "cantidad": 1, "precio_unitario": 89.0 } ],
    "diferencia": 0.0,           // valor_entregado - (valor_devuelto - recargo). > 0 paga el cliente; < 0 queda a su favor
    "forma_cobro": null,         // "EFECTIVO" obligatorio si diferencia > 0
    "observacion": null
  }
}
```
- `valor_devuelto` usa el **precio pagado en la venta original**; `valor_entregado`, el `precio_unitario` informado (el del catálogo del dispositivo).
- Si la venta original también fue offline, envía la `VENTA` antes que el `CAMBIO` (o en el mismo lote: el servidor procesa por `creado_en`).

**Resultado `CONFIRMADA`** — `servidor_id` = id de la solicitud y `detalle`:
```json
{ "codigo": "DEV-000045", "resolucion": "CAMBIO_VARIANTE",    // CAMBIO_PRODUCTO si se entrega otro modelo
  "valor_devuelto": 89.0, "recargo": 0.0, "valor_entregado": 89.0, "diferencia_calculada": 0.0,
  "monto_cobrado": 0.0,
  "nota_credito": null,           // { "codigo": "NC-000012", "monto": 40.0, "vence_en": "..." } si la diferencia fue a favor
  "advertencias": [] }            // p. ej. el cliente superó el máximo mensual de devoluciones (queda marcado para revisión)
```
Se crea la solicitud ya cerrada (`CAMBIO_REALIZADO`, `canal: "OFFLINE"`, visible en `/devoluciones/solicitudes`): la prenda devuelta vuelve al stock vendible (o a no disponible si es `NO_APTA`), la entregada sale del stock y todo queda en movimientos de inventario. La fecha del cambio es `creado_en`, así que el cobro en efectivo entra al **arqueo de la caja** del turno en que ocurrió.

**`CONFLICTO`**: no hay stock central de alguna prenda a entregar (`detalle.items` como en 6.2). No se toca nada; se resuelve en la web (6.4).

**`RECHAZADA`** (mismas reglas que el cambio en línea, contadas a la fecha `creado_en`):
- falta `orden_id`/`venta_uuid` o vienen los dos; venta inexistente o de otra empresa ("Venta no encontrada"); la venta offline original quedó en conflicto o rechazada;
- venta no pagada; fecha del cambio anterior a la venta; fuera de plazo (si la política es `RECARGO`, se acepta con recargo incluido en la diferencia);
- prenda que no pertenece a la venta o más unidades que las elegibles (vendidas − ya devueltas); categoría no retornable sin motivo `DEFECTO`; `NO_APTA` sin motivo `DEFECTO`; máximo de cambios por prenda alcanzado;
- `diferencia` distinta de la calculada (tolerancia 0.01; `detalle` trae `diferencia_calculada`); diferencia a pagar sin `forma_cobro: "EFECTIVO"`.

**En el dispositivo:** validar con `politica_devoluciones` y `ventas_recientes` antes de registrar (plazo, elegibles = `cantidad − devuelto`, retornable, máximo de cambios), descontar del stock local la prenda entregada y sumar la devuelta si es apta, y sumar a `devuelto` de la línea para no permitir cambiar dos veces la misma unidad.

---

## 7. Reportes generativos con IA ✅ (solo web)

**Acceso:** Administrador y Encargado de una empresa con plan **Profesional** y suscripción vigente. Si no se cumple, responde 403 con `detail`; en ese caso oculta el menú usando `funciones.reportes_ia`. El Encargado solo ve su sucursal: el backend lo fuerza y lo avisa en `supuestos`.

**Cómo funciona:**
1. La IA (Gemini) solo traduce el pedido a una **intención** JSON; nunca ve las ventas ni escribe SQL.
2. El backend valida esa intención contra un catálogo cerrado y la ejecuta con consultas propias, filtradas por empresa.
3. Si Gemini no responde (sin internet o sin cuota), un intérprete por reglas resuelve los mismos pedidos. Se distingue por `interprete: "reglas"`.

| Método | Ruta | Uso |
|---|---|---|
| GET | `/ia/reportes/tipos` | Catálogo de reportes, ejemplos, `paleta` de colores e `ia_disponible` |
| POST | `/ia/reportes` | `{"texto": "...", "narrativa": true}` → interpreta, ejecuta y redacta un resumen |
| POST | `/ia/reportes/ejecutar` | `{"intencion": {...}}` → vuelve a ejecutar con filtros editados, **sin IA**. Responde 422 con `detail` si algo no es válido |
| POST | `/ia/reportes/exportar` | `{"intencion": {...}, "formato": "pdf" \| "xlsx", "narrativa": "..."}` → archivo. Pedirlo con `responseType: 'blob'`; el nombre viene en `Content-Disposition` |
| POST | `/ia/generar-reporte` | **Obsoleto** (pantalla vieja). Reemplazar por `/ia/reportes` |

### 7.1 Tipos de reporte
- `ventas_por_periodo`: por día, semana o mes. Gráfico de **líneas**.
- `ventas_por_sucursal`: con `agrupacion` compara las sucursales en el tiempo, con una columna por sucursal. Gráfico de **barras**.
- `productos_mas_vendidos`: ranking. **Barras** horizontales.
- `ingresos_por_categoria`: **torta**.
- `stock_bajo`: stock actual; no usa fechas. **Barras**.
- `devoluciones_por_motivo`: solicitudes de devolución o cambio por motivo, en un período. **Barras**.
- `prediccion_demanda` (ML): fechas **futuras**, por defecto de mañana a 7 días y como máximo 28. Muestra unidades estimadas, rango, stock, cobertura y alerta. **Barras**.
- `segmentos_clientes` (ML): toda la empresa; no usa fechas ni sucursal. **Torta**.
- `evaluacion_modelos` (ML): tabla de métricas, sin gráfico.

Los reportes de ML necesitan un modelo entrenado. Si no existe, se entrena solo la primera vez, y tarda unos 7 s.

### 7.2 Intención (lo que se edita en los filtros)
```json
{ "tipo": "ventas_por_sucursal", "fecha_desde": "2026-09-01", "fecha_hasta": "2026-09-30",
  "agrupacion": "mes",            // "dia" | "semana" | "mes" | null
  "sucursal_ids": [3], "categoria_ids": [], "prenda_ids": [],
  "canal": null,                  // "WEB" | "PRESENCIAL" | "OFFLINE" | null
  "limite": 10, "grafico": "barras" }   // "barras" | "lineas" | "torta" | "tabla"
```
Listas para los selectores de filtros (ya existen): `GET /catalogo/sucursales` (activas), `GET /catalogo/categorias` y `GET /catalogo/` (prendas).

### 7.3 Respuesta de `POST /ia/reportes`
```json
{
  "estado": "OK",                 // "OK" | "ACLARACION" | "NO_SOPORTADO"
  "texto": "ventas de septiembre por sucursal",
  "interprete": "gemini",         // "gemini" | "reglas"
  "intencion": { ... },           // la intención ya validada y completada (null si no es OK)
  "supuestos": ["No se indicó un período: se usó el mes actual."],
  "mensaje": null,                // en ACLARACION / NO_SOPORTADO: texto para el usuario
  "sugerencias": [],              // en ACLARACION / NO_SOPORTADO: ejemplos para mostrar como chips
  "narrativa": "Las ventas de septiembre…", "narrativa_origen": "gemini",
  "reporte": {
    "tipo": "ventas_por_sucursal", "titulo": "Ventas por sucursal", "subtitulo": "Del 01/09/2026 al 30/09/2026",
    "empresa": "Estilo Urbano S.R.L.", "generado_por": "Admin Estilo Urbano", "generado_en": "2026-11-04T14:30:00Z",
    "filtros": [ { "campo": "Período", "valor": "01/09/2026 al 30/09/2026" }, { "campo": "Sucursales", "valor": "Todas" } ],
    "supuestos": [ ... ],
    "columnas": [ { "clave": "sucursal", "titulo": "Sucursal", "tipo": "texto" },
                  { "clave": "monto", "titulo": "Monto (Bs)", "tipo": "moneda" } ],   // tipo: texto | entero | moneda | porcentaje
    "filas": [ { "sucursal": "Estilo Urbano - Equipetrol", "ventas": 245, "unidades": 390, "monto": 70119.2, "participacion": 43.4 } ],
    "totales": { "sucursal": "Total", "monto": 161410.1, ... },                   // null en stock_bajo
    "grafico": { "tipo": "barras", "eje_x": "sucursal", "series": [ { "clave": "monto", "titulo": "Monto (Bs)" } ] },
    "vacio": false
  }
}
```

### 7.4 Pantalla sugerida (web)
- **Caja de texto con botón de micrófono.** La voz se transcribe en el navegador con la Web Speech API (`webkitSpeechRecognition`, `lang: 'es-BO'`) y se envía como `texto`. Si el navegador no la soporta, se oculta el botón.
- **Mientras espera:** indicador de carga, porque puede tardar de 3 a 15 s.
- **Resultados:**
  - Insignia "IA" o "Reglas" según `interprete`.
  - Los `supuestos` como notas.
  - Si el estado no es OK, el `mensaje` y las `sugerencias` como chips clicables.
- **Tabla:** se arma con `columnas`. Las columnas `moneda` usan formato `1.234,50`, `porcentaje` usa `12,5 %` y los números van alineados a la derecha. La fila `totales` va en negrita.
- **Gráfico:**
  - Se arma desde `grafico`: el eje X es `filas[eje_x]` y hay una serie por cada elemento de `series`.
  - Los colores son los de `paleta`, **en orden y sin rotarlos**: la serie *i* usa `paleta[i]`.
  - Con 2 o más series se muestra la leyenda.
  - Selector para cambiar el tipo de gráfico.
- **Filtros editables** (fechas, sucursales, categorías, agrupación, canal, límite) que llaman a `/ia/reportes/ejecutar` sin gastar IA.
- **Botones "PDF" y "Excel"** (`/ia/reportes/exportar`), que envían la `intencion` actual y la `narrativa` mostrada.

---

## 8. Analítica inteligente con Machine Learning ✅ (solo web)

**Acceso:** igual que los reportes IA: plan **Profesional**, Administrador y Encargado. El Encargado ve solo su sucursal, porque el backend la fuerza. **Solo el Administrador entrena.**
**Modelos por empresa:** cada empresa entrena solo con sus propios datos. Si no tiene historial suficiente (84 días y 200 ventas para demanda; 10 clientes con compras para segmentación), responde **409** con `detail`.
**Empresa para la demo:** Estilo Urbano (§1).

| Método | Ruta | Uso |
|---|---|---|
| POST | `/ml/entrenar` | Entrena demanda y segmentación (unos 7 s). Devuelve `{demanda: {...}, segmentacion: {...}}`, cada uno con `version`, `algoritmo`, `entrenado_en`, `parametros`, `datos` y `metricas`, o con `{error}` si ese modelo no tiene datos |
| GET | `/ml/modelos` | Modelos activos, con el mismo formato pero sin el binario |
| GET | `/ml/demanda?dias=7&sucursal_id=&categoria_id=` | Predicción desde hoy (`dias` de 1 a 28) |
| GET | `/ml/reposicion?sucursal_id=&limite=10` | Variantes (talla/color) que se agotarían antes de 14 días |
| GET | `/ml/segmentos` | Segmentos y la asignación de cada cliente |
| GET | `/ml/dashboard?sucursal_id=` | Todo lo necesario para el dashboard analítico |

### 8.1 Modelos (para mostrar en la pantalla "Modelos" y para la defensa)
- **Demanda (supervisado):** `HistGradientBoostingRegressor` con pérdida Poisson.
  - **Predice:** las unidades por día, sucursal y categoría.
  - **Validación temporal:** las últimas 4 semanas como prueba, más una validación cruzada de 3 bloques.
  - **Comparación:** contra el método simple (promedio del mismo día de la semana).
  - **Métricas** en `metricas.prueba`: `mae`, `rmse`, `r2`, `mae_metodo_simple`, `mejora_vs_simple_pct`, `error_total_pct`, `unidades_reales` y `unidades_predichas`.
  - **Variables:** `metricas.importancias` trae `[{variable, importancia}]` por permutación. `parametros.variables_descartadas` trae `[{variable, motivo}]`.
- **Segmentación (no supervisado):** K-Means sobre variables RFM.
  - **Variables:** recencia, frecuencia, monto, ticket promedio y % de productos caros.
  - **k:** se elige entre 2 y 6 con el coeficiente de silueta.
  - **Métricas:** `k`, `silueta`, `davies_bouldin`, `curva` (`[{k, silueta, inercia}]`, que se grafica para justificar k) y `ari_perfiles_sinteticos` (comparación con los perfiles con que se generaron los datos).

### 8.2 `GET /ml/demanda`
```json
{ "modelo": {"version": 3, "entrenado_en": "2026-11-04T15:00:00Z"}, "desde": "2026-11-04", "hasta": "2026-11-10",
  "filas": [ { "sucursal_id": 3, "categoria_id": 11, "sucursal": "Estilo Urbano - Equipetrol", "categoria": "Poleras",
               "unidades": 31.4, "minimo": 24, "maximo": 39, "promedio_diario": 4.49,
               "stock": 382, "cobertura_dias": 85.2, "alerta": "OK" } ],     // alerta: CRÍTICO (<7 días) | ATENCIÓN (<14) | OK | — (web: sin stock propio)
  "diario": [ { "fecha": "2026-11-04", "prediccion": 36.2, "minimo": 29, "maximo": 44 } ] }
```

### 8.3 `GET /ml/segmentos`
```json
{ "modelo": { "version": 3, "entrenado_en": "...", "metricas": { ... } },
  "segmentos": [ { "segmento": "Premium", "clientes": 9, "porcentaje": 18.0, "recencia_dias": 5.1, "frecuencia": 33.7,
                   "monto_total": 14301.46, "ticket_promedio": 422.59, "pct_premium": 49.6,
                   "descripcion": "Compran productos de mayor precio…", "accion_sugerida": "Ofrecer lanzamientos…" } ],
  "clientes": [ { "cliente_id": 61, "nombre": "…", "email": "…", "segmento": "Premium", "recencia_dias": 3,
                  "frecuencia": 35, "monto_total": 15210.0, "ticket_promedio": 434.57, "pct_premium": 0.52 } ] }
```
Nombres posibles de segmento: Premium, Frecuentes, Ocasionales, En riesgo, Inactivos. Si hay dos con el mismo nombre, llevan sufijo " (2)".

### 8.4 `GET /ml/dashboard`
```json
{ "generado_en": "2026-11-04", "comparacion": "01/11–03/11 contra 01/10–03/10",
  "indicadores": { "ventas_mes": {"valor": 18398.1, "anterior": 21000.0, "variacion_pct": -12.4},
                   "cantidad_ventas_mes": {...}, "ticket_promedio": {...}, "unidades_mes": {...},
                   "clientes_activos_30_dias": {...} },
  "serie": [ { "fecha": "2026-09-05", "real": 41, "prediccion": null, "minimo": null, "maximo": null },
             { "fecha": "2026-11-04", "real": null, "prediccion": 36.2, "minimo": 29, "maximo": 44 } ],   // 60 días reales + 14 predichos (unidades)
  "segmentos": [ ...como en 8.3... ],
  "alertas_reposicion": [ { "producto": "Jean Slim Piraí", "talla": "28", "color": "Negro", "sucursal": "…", "stock": 0,
                            "demanda_diaria": 0.31, "cobertura_dias": 0.0, "sugerido_reponer": 9, "alerta": "CRÍTICO" } ],
  "modelos": { "demanda": {...como /ml/modelos...}, "segmentacion": {...} },
  "avisos": [] }    // mensajes si algún modelo no pudo entrenarse (sin datos suficientes)
```

### 8.5 Pantalla sugerida: "Analítica"
1. **Indicadores (KPI):** el valor y la variación contra el mes anterior, con una flecha y el texto de `comparacion`.
2. **Gráfico de línea:** la `serie` real en línea continua y la predicción en línea punteada, con una banda sombreada entre `minimo` y `maximo`. El eje Y está en unidades por día. Marcar "hoy".
3. **Segmentos:** torta o barras, más tarjetas con la descripción y la acción sugerida.
4. **Alertas de reposición:** tabla con insignias CRÍTICO/ATENCIÓN y unidades sugeridas.
5. **Modelos** (pestaña o sección):
   - métricas con explicación;
   - barras de importancia de variables;
   - curva de silueta por k;
   - variables descartadas;
   - botón **"Reentrenar"**, solo para el Administrador, con indicador de carga.
6. Colores: `paleta` de `GET /ia/reportes/tipos`, en orden y sin rotarlos. Para alertas, usar ícono + texto (no solo color).

---

## 9. Devoluciones y cambios (CU-01 a CU-11) y caja (CU-20) ✅ (web)

Están disponibles en los dos planes. Roles:
- **Cajero:** registra solicitudes y resuelve (cambio, reembolso, sin stock).
- **Encargado y Administrador:** además inspeccionan y autorizan.
- **Cliente:** solicita desde "Mis compras" y ve sus solicitudes y sus notas de crédito.
- **Administrador:** configura la política.

El Cajero y el Encargado solo ven las solicitudes de su sucursal. Una solicitud o venta de otra empresa responde **404**.

### 9.1 Endpoints `/devoluciones`
| Método | Ruta | Quién | Uso |
|---|---|---|---|
| GET | `/politica` | todos | Política vigente (CU-09) |
| PUT | `/politica` | Administrador | `{plazo_cambio_dias, plazo_garantia_dias, categorias_no_retornables: [ids], max_cambios_por_prenda, max_devoluciones_mes_cliente, fuera_de_plazo: "RECHAZAR"\|"RECARGO", recargo_pct, vigencia_nota_credito_dias, umbral_diferencia_caja}` |
| GET | `/ventas?orden_id=` o `?cliente=texto` | personal | Buscar la venta por número de comprobante o por datos del cliente. Ver 9.2 |
| GET | `/mis-compras` | Cliente | Sus compras con las prendas elegibles |
| POST | `/solicitudes` | personal, Cliente | `{orden_id, items: [{detalle_orden_id, cantidad}], motivo, resolucion, sucursal_id?, observacion?}` → **201**. Ver 9.3 |
| GET | `/solicitudes?estado=&sucursal_id=&motivo=&desde=&hasta=` | todos | Historial más `totales` (CU-11) |
| GET | `/solicitudes/{codigo}` | todos | Detalle, con `acciones` posibles para el usuario |
| POST | `/solicitudes/{codigo}/autorizar` | Encargado, Administrador | Si `requiere_autorizacion` (el cliente superó el máximo mensual) |
| POST | `/solicitudes/{codigo}/inspeccionar` | Encargado, Administrador | `{resultado: APTA\|APTA_CON_DESCUENTO\|NO_APTA\|INCOMPLETA\|RECHAZAR, observacion}`. Para RECHAZAR, la observación es obligatoria (CU-03) |
| POST | `/solicitudes/{codigo}/cambio-variante` | personal | `{items: [{detalle_id, variante_id}], forma_cobro?}` → otra talla o color del mismo modelo (CU-04) |
| POST | `/solicitudes/{codigo}/cambio-producto` | personal | `{items: [{variante_id, cantidad}], forma_cobro?}` (CU-05). Si el producto nuevo cuesta más, `forma_cobro` es obligatoria; si cuesta menos, se emite una nota de crédito por la diferencia |
| POST | `/solicitudes/{codigo}/reembolso` | personal | `{forma: EFECTIVO\|MEDIO_ORIGINAL\|NOTA_CREDITO}` (CU-06). Si la venta fue con QR, tarjeta o Stripe y se elige MEDIO_ORIGINAL, queda `reembolso_pendiente_procesador: true` |
| POST | `/solicitudes/{codigo}/sin-stock` | personal | `{decision: NOTA_CREDITO\|ESPERAR_STOCK}` (CU-08) |
| GET | `/disponibilidad/{variante_id}` | personal | Stock del mismo modelo en todas las sucursales (CU-08) |
| GET | `/notas-credito` · `/notas-credito/{codigo}` | todos (el Cliente, solo las suyas) | Saldo, vencimiento, estado (VIGENTE\|USADA\|VENCIDA) y movimientos (CU-07) |

**Motivos:** `TALLA`, `AJUSTE_MEDIDA`, `COLOR`, `DEFECTO`, `PRODUCTO_EQUIVOCADO`, `YA_NO_LO_DESEA`.
**Resolución pedida:** `CAMBIO_VARIANTE`, `CAMBIO_PRODUCTO`, `REEMBOLSO`. En la resolución final se puede elegir otra.

**Estados:** `EN_INSPECCION` → `INSPECCIONADA` → `CAMBIO_REALIZADO`, `REEMBOLSADA`, `CERRADA_CON_NOTA` o `RECHAZADA`.
- Además existe `PENDIENTE_STOCK`. Desde ahí se puede hacer el cambio cuando llegue el stock, o emitir una nota.
- El campo `acciones` de cada solicitud dice qué botones mostrar: `AUTORIZAR`, `INSPECCIONAR`, `CAMBIO_VARIANTE`, `CAMBIO_PRODUCTO`, `REEMBOLSO` y `SIN_STOCK`.

**Reglas del servidor** (los errores llegan como 409 con `detail` legible):
- **Venta:** tiene que estar pagada.
- **Plazo:** desde la fecha de la venta; para `DEFECTO` se usa el plazo de garantía. Si está fuera de plazo y la política es RECHAZAR, el mensaje incluye la fecha límite. Si la política es RECARGO, se descuenta `recargo` del monto a favor.
- **Cantidad:** no puede superar lo vendido menos lo ya devuelto.
- **Categorías no retornables:** solo se aceptan por `DEFECTO`.
- **Cambios:** hay un máximo de cambios por prenda.
- **Stock:** si no alcanza para entregar la prenda de cambio, responde 409 "Sin stock…". En ese caso conviene ofrecer `disponibilidad` y `sin-stock`.

**Inventario (CU-10):**
- La prenda devuelta suma stock vendible si es `APTA` o `APTA_CON_DESCUENTO`; si no, va a `stock_no_disponible`.
- La prenda entregada se descuenta.
- Cada movimiento queda registrado en `movimientos_inventario`.

### 9.2 Venta para devolver (`GET /ventas`, `GET /mis-compras`)
```json
{ "orden_id": 3498, "fecha": "2026-11-04T15:20:00Z", "canal": "PRESENCIAL", "metodo_pago": "EFECTIVO", "sucursal": "…",
  "nombre_cliente": "…", "total": 79.0, "limite_cambio": "2026-12-04", "limite_garantia": "2027-02-02",
  "items": [ { "detalle_orden_id": 7001, "prenda": "Polera Básica Algodón", "talla": "M", "color": "Negro", "cantidad": 1,
               "precio_unitario": 79.0, "devuelto": 0, "elegible": 1, "cambios_realizados": 0, "retornable": true } ] }
```

### 9.3 Solicitud (respuesta de todas las operaciones)
```json
{ "codigo": "DEV-000001", "estado": "INSPECCIONADA", "orden_id": 3498, "canal": "TIENDA", "cliente": null,
  "sucursal": {"id": 4, "nombre": "…"}, "motivo": "TALLA", "motivo_texto": "No le quedó la talla",
  "resolucion_pedida": "CAMBIO_VARIANTE", "creado_en": "…", "requiere_autorizacion": false, "autorizada": false,
  "fuera_de_plazo": false, "recargo": 0, "inspeccion": "APTA", "observacion": null,
  "valor_devuelto": 79.0, "monto_a_favor": 79.0, "resolucion": null, "monto_reembolsado": 0, "forma_reembolso": null,
  "reembolso_pendiente_procesador": false, "monto_cobrado": 0, "forma_cobro": null, "entregas": [],
  "nota_credito": null,   // {codigo, monto, saldo, vence_en} si se emitió
  "items": [ { "id": 1, "detalle_orden_id": 7001, "variante_id": 10, "prenda": "…", "talla": "M", "color": "Negro",
               "cantidad": 1, "precio_unitario": 79.0, "entregado": null } ],
  "acciones": ["CAMBIO_VARIANTE", "CAMBIO_PRODUCTO", "REEMBOLSO", "SIN_STOCK"] }
```

### 9.4 Nota de crédito como forma de pago
`POST /catalogo/checkout/presencial` acepta `"nota_credito": "NC-000001"`.
- Se aplica el saldo, hasta el total de la venta. Lo que falte se paga con `metodo_pago`, es decir, el pago puede ser mixto.
- La respuesta agrega `pagado_con_nota_credito` y `a_pagar`.
- Si la nota está vencida, usada o es de otro cliente, responde 409.

### 9.5 Caja `/caja` (CU-20)
| Método | Ruta | Uso |
|---|---|---|
| POST | `/abrir` | `{fondo_inicial, sucursal_id?}`. `sucursal_id` solo lo envía el Administrador. Responde 409 si ya hay una caja abierta en la sucursal |
| GET | `/actual?sucursal_id=` | Caja abierta con `arqueo` en vivo. Responde 404 si no hay ninguna |
| POST | `/cerrar?sucursal_id=` | `{efectivo_contado, observacion?, pendientes_locales?: {cantidad, monto_efectivo}}`. Ver las reglas abajo |
| POST | `/{id}/autorizar` | Encargado o Administrador |
| GET | `/turnos?sucursal_id=` | Historial de turnos |

**Arqueo:**
- `fondo_inicial` y `efectivo_esperado`;
- `ventas_efectivo`: presenciales y offline ya sincronizadas, menos lo pagado con nota de crédito;
- `cobros_cambios_efectivo` y `reembolsos_efectivo`;
- `ventas.por_metodo`, con las ventas por QR o tarjeta solo como información;
- `ventas.offline_sincronizadas`.

**Reglas del cierre:**
- Si hay diferencia, la observación es obligatoria; sin ella responde 422.
- Si la diferencia supera `umbral_diferencia_caja` de la política (50 por defecto) y cierra un Cajero, la caja queda `PENDIENTE_AUTORIZACION`.
- Para cerrar en el dispositivo: enviar en `pendientes_locales` las ventas que el dispositivo todavía tiene en LOCAL. Se concilian al sincronizar, porque la venta offline guarda su hora real.
