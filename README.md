# Platform Infrastructure - Sistema Médico-Odontológico

Infraestructura compartida, configuración de API Gateway, contratos de integración y especificaciones de componentes distribuidos para el sistema médico-odontológico.

---

## 1. Mapa de Servicios y Puertos

| Componente | Rol en el Sistema | Responsable | Tecnología | Puerto | Prefijo en Gateway | Estado |
|---|---|---|---|---|---|---|
| **API Gateway** | Puerta de enlace unificada | Infraestructura | Nginx (Windows) | `80` | `/` | **Activo** |
| **MS1** | Seguridad y Autenticación | Dennis | Spring Boot | `8081` | `/api/seguridad/` | En desarrollo |
| **MS2** | Expediente Clínico e IA | Henry | NestJS + MongoDB | `3001` | `/api/expediente/` | Funcional con MongoDB |
| **MS3** | Agendamiento y Citas | Wendy | Laravel | `8001` | `/api/agendamiento/` | En desarrollo |
| **RabbitMQ** | Bus de Eventos EDA | Asíncrono | Message Broker | `5672` / `15672` | - | Planificado (Sin instalar) |
| **Keycloak** | IAM y SSO OIDC | Seguridad central | Auth Server | `8080` | - | Planificado (Sin instalar) |
| **MCP Server**| Contexto de IA Clínica | IA / MS2 | Model Context Protocol | `3100` | - | Planificado (Sin instalar) |

---

## 2. Estructura del Repositorio

```text
platform-infrastructure/
├── contracts/                  # Contratos y convenciones de integración
│   ├── README.md               # Convenciones de IDs (UUID), RFC 7807, X-Idempotency-Key
│   ├── graphql/                # Esquemas GraphQL (ERP / Finanzas)
│   │   ├── README.md           # Guía de arquitectura GraphQL vs REST
│   │   └── ms1-erp.graphql     # Esquema SDL para MS1 ERP (Dennis)
│   └── rest/                   # Especificaciones OpenAPI 3.0 por microservicio
│       ├── ms1-seguridad.yaml  # REST preliminar de seguridad (Dennis)
│       ├── ms2-clinico.yaml    # Expediente, consultas, odontograma, recetas (Henry)
│       └── ms3-agendamiento.yaml # Citas, disponibilidad y stock clínico (Wendy)
├── gateway/                    # Configuración de Gateways
│   └── nginx/                  # Nginx para Windows
│       ├── README.md           # Guía de instalación y ciclo de vida de Nginx
│       └── gateway.conf        # Configuración de proxies inversos por prefijo
├── identity/                   # Servicios de identidad
│   └── keycloak/               # IAM OIDC / OAuth2
│       ├── README.md           # Responsabilidades y roles
│       └── realm-config.example.json # Plantilla de configuración de realm
├── messaging/                  # Mensajería asíncrona
│   └── rabbitmq/               # RabbitMQ Broker
│       ├── README.md           # Responsabilidades y arquitectura de eventos
│       └── topology.json       # Topología declarativa de exchanges y colas
├── mcp/                        # Servidor Model Context Protocol para IA
│   ├── README.md               # Responsabilidades, Tools y Resources clínicos
│   └── server/                 # Espacio reservado para el servidor MCP
└── scripts/                    # Scripts de soporte y diagnóstico
    ├── check-ports.ps1         # Comprobación de puertos 80, 8081, 3001, 8001
    └── test-gateway.ps1        # Test de conectividad a través de Nginx
```

---

## 3. Inicio Rápido para Desarrolladores

### 1. Comprobar Puertos Locales
Abre una terminal PowerShell y ejecuta:
```powershell
.\scripts\check-ports.ps1
```

### 2. Probar Enrutamiento del Gateway
Para probar si Nginx y los microservicios responden:
```powershell
.\scripts\test-gateway.ps1
```

### 3. Operación de Nginx en Windows
Consulta la guía completa en [gateway/nginx/README.md](file:///c:/2-2026/sw2/p2/platform-infrastructure/gateway/nginx/README.md).
```powershell
# Validar configuración
cd C:\nginx; .\nginx.exe -t

# Iniciar
start nginx

# Recargar cambios
.\nginx.exe -s reload
```
