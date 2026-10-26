# Identidad Keycloak: compatibilidad legacy y ERP

**Configuración preparada, sin aprovisionar servicios.** El ERP usa un realm separado
`dental-platform`; la plantilla legacy no cambia. Importar o modificar una instancia
compartida requiere autorización: estos archivos no despliegan ni reinician Keycloak.

## 1. Elegir el realm sin romper otros servicios

| Plantilla | Realm | Consumidores y roles |
|---|---|---|
| [realm-config.example.json](realm-config.example.json) | `odontoclinic-realm` | Contrato legacy de MS1/MS2/MS3 y portal: `ROLE_ADMIN`, `ROLE_DENTISTA`, `ROLE_ASISTENTE`, `ROLE_RECEPCIONISTA`, `ROLE_PACIENTE` |
| [dental-platform-realm.example.json](dental-platform-realm.example.json) | `dental-platform` | ERP: `ADMIN`, `RECEPCIONISTA`, `CAJERO`, `ODONTOLOGO` |

Se conservan todos los clientes legacy: `web-portal-frontend`,
`ms1-seguridad-service`, `ms2-expediente-service` y `ms3-agendamiento-service`.
El JSON legacy define los tres servicios como **bearer-only**, no como clientes
confidenciales con client credentials. No se endurecen sus flujos ni se migran sus
usuarios a ciegas; tampoco se afirma compatibilidad SSO entre realms diferentes.
El puerto previsto del Keycloak legacy sigue siendo `8080`.

El ERP lee `realm_access.roles` y antepone `ROLE_` en el backend. Por eso recibe
`ADMIN`, no `ROLE_ADMIN`: este último produciría `ROLE_ROLE_ADMIN` y fallaría la
autorización. No hay equivalencia automática entre `DENTISTA` y `ODONTOLOGO` ni
entre roles de ambos realms. El principal usa `preferred_username`; la auditoría
resuelve el usuario de BD por subject (`keycloak_id`) o por ese nombre. Asignar
roles y vincular identidades con los usuarios activos de BD sigue siendo una tarea
administrativa autorizada; esta plantilla no incluye usuarios, contraseñas ni secretos.

## 2. Camino de integración ERP (tras autorización)

1. Preparar una instancia aislada con el realm ERP, sin reemplazar el legacy.
   El ejemplo local usa Keycloak en `http://localhost:8180`, independiente del
   puerto `8080` previsto para el legacy. HTTP es solo para desarrollo local;
   en entornos compartidos se requiere HTTPS y orígenes aprobados.
2. Configurar el frontend con issuer
   `http://localhost:8180/realms/dental-platform`, cliente `mf-erp`,
   `response_type=code`, `scope=openid profile` y PKCE **S256** obligatorio.
   Redirect y logout: `http://localhost:4201/` (rutas bajo ese origen).
3. Enviar el **access token**, no el ID token, como `Authorization: Bearer <token>`
   al ERP detrás del Gateway. No usar password grant ni `X-Dev-User` para integrar.
4. Fijar `ERP_PORT=8081` y la variable de issuer correspondiente al modo de abajo.
   Verificar discovery, JWKS y JWT antes de declarar funcional la integración.

`mf-erp` es público, sin secreto, con authorization code y sin flujo implícito,
direct access grants ni service account. Solo permite origen
`http://localhost:4201`; no usa `*` ni `+` para web origins. Los scopes estándar
`profile` y `roles` aportan `preferred_username` y `realm_access.roles` en Keycloak.
El mapper agrega audiencia `ms-erp` al access token, no al ID token. La plantilla
no incorpora el cliente de password grant para pruebas del backend.

## 3. Variables reales y conectividad

| Modo backend | Variable de issuer | Puerto ERP |
|---|---|---|
| Cadena JWT normal (sin bypass) | `KEYCLOAK_ISSUER_URI=http://localhost:8180/realms/dental-platform` | `ERP_PORT=8081` (también es su valor predeterminado normal) |
| Perfil `local`, cadena local con Bearer | `ERP_LOCAL_JWT_ISSUER_URI=http://localhost:8180/realms/dental-platform` | `ERP_PORT=8081` explícito: el perfil local tiene predeterminado `8080` |

`KEYCLOAK_ISSUER_URI` configura el resource server normal; no sustituye a
`ERP_LOCAL_JWT_ISSUER_URI` cuando está activa la cadena local. En esta última,
un issuer vacío deshabilita Bearer; no es una solución. La resolución local es
perezosa y un issuer inaccesible rechaza Bearer con `401` hasta poder resolverlo;
las claves ya cacheadas pueden seguir validando tokens. No confundir esto con
una prueba de disponibilidad continua del proveedor.

**Issuer público no es sinónimo de dirección interna del contenedor.** El claim
`iss`, el issuer configurado y el issuer anunciado por discovery deben coincidir
exactamente (esquema, host, puerto y realm). Discovery vive en
`<issuer>/.well-known/openid-configuration`; su `jwks_uri` debe ser accesible
desde el ERP. El navegador también debe llegar al issuer público.

- **Mismo host:** `localhost:8180` funciona si navegador, ERP y Keycloak tienen
  acceso a ese puerto en el mismo host. `127.0.0.1` siempre es loopback del proceso.
- **Entre contenedores:** `127.0.0.1` apunta al propio contenedor, no a Keycloak
  ni al host. Usar un nombre público estable con resolución/ruteo adecuados
  desde navegador y backend (por ejemplo DNS dividido o proxy autorizado).
  Configurar el hostname público anunciado por Keycloak de forma coherente.
  No sustituir solo el issuer backend por `http://keycloak:8080/realms/dental-platform`
  si los tokens dicen `http://localhost:8180/realms/dental-platform`.
- No se agrega una variable ficticia para separar JWKS interno del issuer.
  El backend publicado usa discovery del issuer; la ruta al documento y a sus
  claves debe resolverse sin desactivar validación de firma ni de issuer.

El perfil local soporta `X-Dev-User`, y existe además un modo dev con permisos
amplios; **ninguno es una solución de integración**. No habilitar
`erp.security.dev-mode`, no enviar `X-Dev-User` como sustituto del JWT y no cambiar
seguridad para hacer pasar pruebas. Un Bearer inválido no debe caer en ese header.

## 4. Límites y verificación pendiente

El backend publicado **no valida la audiencia**. Emitir `aud: ms-erp` prepara el
contrato, pero no garantiza aislamiento frente a tokens de otros clientes del
mismo realm. Corregir ese límite requiere un cambio backend autorizado, fuera de
esta unidad; no se debe presentar el mapper como enforcement del receptor.

Verificación estructural, sin red ni servicios:

```bash
python -m unittest discover -s scripts/tests -p test_identity.py -v
```

Las pruebas comprueban separación de realms, preservación legacy, roles crudos,
PKCE, flujos deshabilitados, origen explícito, mapper y ausencia de credenciales.
No demuestran una importación real ni emisión/verificación criptográfica de JWT.
Antes de un uso compartido quedan pendientes, en entorno aislado autorizado:
importación sin alterar el realm legacy, discovery/JWKS desde el ERP, login PKCE,
JWT válido, rechazo de issuer/firma/expiración inválidos, autorización por rol y
vínculo de auditoría con BD. No ejecutar estas comprobaciones sobre datos reales
ni instalar herramientas o levantar servicios sin permiso.

Referencia de compatibilidad: ms-erp publicado en
`c6abae67109719113a2767e547ff0fce5553c740`, documentación de Keycloak local,
`SecurityConfig`, `KeycloakRealmRoleConverter`, `LazyIssuerJwtDecoder` y
configuración de perfiles. No se copia su semilla de usuarios ni sus credenciales.
