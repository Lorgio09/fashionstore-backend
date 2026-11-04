# Contrato API — FashionStore SaaS (parcial 2)

Versión 3 · 2026-11-04 · Fuente única para la PWA (Angular) y la app móvil (Flutter).
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
| Producción (Render) | `https://fashionstore-api-kedu.onrender.com/api` — **todavía con la versión vieja**; no usar hasta que se migre |

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
- **Visitante anónimo (tienda pública):** enviar el header `X-Empresa: <slug>` (ej. `moda-andina`). Sin header se usa `fashionstore`. Si hay token, el token manda y el header se ignora.
- Un recurso de otra empresa responde **404** (no se revela que existe).

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
| `POST /reservas/` | **Requiere token.** `cliente_id` opcional: si es Cliente se usa su id; si es personal, obligatorio |
| `GET /reservas/sucursal/{id}`, `PUT /reservas/{id}/estado` | Personal |
| `GET /reservas/cliente/{id}` | Token; un Cliente solo ve las suyas |
| `GET /usuarios/`, `POST /usuarios/usuarios` | Solo Administrador. Ya no devuelve `password_hash` |
| `GET /auditoria/` | Solo Administrador |
| `POST /ia/generar-reporte` | Administrador/Encargado **y plan Profesional** (403 con plan Básico) |
| Eliminados | `/usuarios/sembrar-datos`, `/catalogo/parche-db`, `/catalogo/migrar-tablas-ordenes`, `/parche-db` |

Las órdenes ahora traen `canal` (`WEB`/`PRESENCIAL`/`OFFLINE`), `metodo_pago`, `sucursal_id`, `usuario_id`, `cliente_id`, `uuid_operacion`.

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
  "clientes": [ { "id": 9, "nombre_completo": "...", "email": "...", "telefono": null } ]   // solo para personal
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
- Si la operación ya no está en conflicto, responde **409**. Si es de otra empresa, responde **404**.

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
