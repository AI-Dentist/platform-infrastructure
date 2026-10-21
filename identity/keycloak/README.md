# Arquitectura de Identidad y Acceso Centralizado: Keycloak

> **ESTADO DEL COMPONENTE: PLANIFICADO (NO INSTALAR EN ESTA FASE)**  
> Este documento describe las responsabilidades, diseño de seguridad y futuras configuraciones para la gestión unificada de identidades y autorización del sistema médico-odontológico. No se debe realizar la instalación local ni levantar servicios hasta contar con la autorización formal.

---

## 1. Responsabilidades en el Ecosistema Distribuido

Keycloak fungirá como el **Servidor de Autorización e Identidad (Identity Provider - IdP)** basado en estándares abiertos **OpenID Connect (OIDC)** y **OAuth 2.0**:

1. **Autenticación Centralizada (Single Sign-On - SSO):**
   - Los usuarios (odontólogos, higienistas, personal de recepción, pacientes y administradores) inician sesión una sola vez para interactuar con los microfrontends y acceder a las APIs de MS1, MS2 y MS3.
2. **Control de Acceso Basado en Roles (RBAC):**
   - Gestión unificada de roles clínicos y administrativos con granularidad de permisos.
   - Los microservicios no almacenan contraseñas; únicamente validan firmas criptográficas de JSON Web Tokens (JWT) mediante claves públicas (JWKS).
3. **Federación e Integración con MS1 (Seguridad):**
   - MS1 (Spring Boot) actuará como backend de integración administrativa o adaptador de seguridad, gestionando perfiles de personal clínico mientras Keycloak centraliza la autenticación, expiración de tokens, refresh tokens y revocación.
4. **Cumplimiento de Privacidad en Salud:**
   - Auditoría de inicios de sesión y accesos no autorizados a datos de pacientes, soportando políticas estrictas de contraseñas y doble factor de autenticación (2FA / MFA).

---

## 2. Definición de Roles del Dominio Clínico

El Realm configurará los siguientes roles canónicos:

| Rol | Alcance de Permisos |
|---|---|
| `ROLE_ADMIN` | Configuración de infraestructura, gestión global de usuarios y auditoría. |
| `ROLE_DENTISTA` | Acceso completo a historias clínicas (MS2), odontogramas, evolución de tratamientos y visualización de su agenda de citas (MS3). |
| `ROLE_ASISTENTE` | Registro de constantes vitales, apoyo en odontograma y visualización de expedientes asignados. |
| `ROLE_RECEPCIONISTA` | Gestión total de agenda de citas (MS3), apertura inicial de ficha de paciente (MS2), sin acceso a detalles clínicos confidenciales. |
| `ROLE_PACIENTE` | Consulta de sus propias citas programadas y descarga de recetas/resúmenes de tratamiento autorizados. |

---

## 3. Especificación de Configuración Futura

Cuando se apruebe la puesta en marcha local de Keycloak:

- **Puerto HTTP previsto:** `8080` (o puerto no colisionante en caso de mapeo en Nginx).
- **Nombre del Realm:** `odontoclinic-realm`
- **Clients Previstos:**
  - `web-portal-frontend` (Public Client / PKCE) para los Microfrontends Web.
  - `ms1-seguridad-service` (Confidential Client / Client Credentials).
  - `ms2-expediente-service` (Bearer-only / Resource Server).
  - `ms3-agendamiento-service` (Bearer-only / Resource Server).
- **Algoritmo de Firma de Token:** `RS256` con rotación periódica de claves asimétricas.
- **Endpoint de Claves Públicas (JWKS):**
  `http://localhost:8080/realms/odontoclinic-realm/protocol/openid-connect/certs`

---

## 4. Estructura del Token JWT Previsto

```json
{
  "iss": "http://localhost:8080/realms/odontoclinic-realm",
  "sub": "e28bbd98-1e43-4dc3-9c8e-5b1234567890",
  "aud": "account",
  "typ": "Bearer",
  "preferred_username": "juan.perez",
  "email": "juan.perez@clinicadental.local",
  "realm_access": {
    "roles": ["ROLE_DENTISTA"]
  },
  "resource_access": {
    "ms2-expediente": {
      "roles": ["expediente:leer", "expediente:escribir"]
    }
  }
}
```

---

## 5. Estado de Implementación

- [x] Documento de diseño arquitectónico y catálogo de roles preparado.
- [ ] Instalación o aprovisionamiento local de Keycloak (Pendiente de autorización).
- [ ] Creación de Realm `odontoclinic-realm` y clientes OIDC.
- [ ] Configuración del Resource Server en Spring Boot (Spring Security OAuth2 Resource Server), NestJS (Passport-JWT) y Laravel (Laravel Sanctum / Passport).
