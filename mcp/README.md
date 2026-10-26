# Arquitectura de Integración de IA: Model Context Protocol (MCP)

> **ESTADO DEL COMPONENTE: PLANIFICADO (NO INSTALAR EN ESTA FASE)**  
> Este documento describe las responsabilidades, protocolos y especificación técnica del servidor MCP diseñado para brindar contexto clínico al módulo de inteligencia artificial de MS2 (`ms2-clinico-ia`). No se debe proceder con la instalación o inicialización del servidor hasta recibir la autorización correspondiente.

## MCP ERP: superficie distinta, ya publicada por ms-erp

El servidor clínico propuesto abajo **no sustituye** al MCP del ERP. El backend
ERP publicado `c6abae67109719113a2767e547ff0fce5553c740` implementa `/mcp` con
**Streamable HTTP**, autenticación Bearer y autorización de herramientas por rol.
El gateway conserva `/mcp` sin reescritura hacia ERP:8081; no usa WebSocket ni el
puerto clínico 3100. Ver [rutas, CORS y streaming](../gateway/nginx/README.md).

Las pruebas del gateway verifican transporte y llegada temprana de eventos SSE
contra mocks, no una negociación/sesión MCP real ni ejecución de herramientas
contra el ERP. No se invocaron proveedores de IA ni datos clínicos reales.

---

## 1. Responsabilidades de MCP en el Dominio Odontológico

El **Model Context Protocol (MCP)** es un estándar abierto que permite a modelos de lenguaje (LLMs) y agentes inteligentes conectarse con fuentes de datos seguras y herramientas de ejecución de manera controlada y desacoplada:

1. **Aislamiento Seguro de Datos Médicos:**
   - Evita que los modelos de lenguaje tengan acceso directo e irrestricto a la base de datos MongoDB de expedientes clínicos.
   - Aplica filtros de anonimización y desidentificación de datos sensibles de pacientes antes de exponerlos al asistente de IA.
2. **Exposición Estandarizada de Recursos Clínicos (Resources):**
   - Expone esquemas de odontograma, catálogos de piezas dentales (nomenclatura FDI / Universal), diccionarios de terminología CIE-10 / SNOMED-CT odontológica.
3. **Herramientas Clínicas Asistidas (Tools):**
   - Brinda herramientas controladas que el modelo puede invocar para calcular índices periodontales, validar incompatibilidades farmacológicas con antecedentes médicos del paciente o generar borradores de evolución clínica.

---

## 2. Relación de MCP con MS2 (`ms2-clinico-ia`)

```text
+-----------------------+          +-------------------------+          +------------------------+
|      MS2 NestJS       |  REST    |  Asistente Clínico IA   |  MCP     |       MCP Server       |
| (Expediente / MongoDB)| <------> |     ms2-clinico-ia      | <------> |     (mcp/server)       |
+-----------------------+          +-------------------------+          +------------------------+
                                                                                    |
                                                                        +-----------+-----------+
                                                                        |                       |
                                                                   [Tools Clínicas]     [Recursos / Guías]
```

1. El profesional odontólogo registra notas u observaciones durante la consulta a través del frontend.
2. **MS2** orquesta la interacción y solicita asistencia al agente.
3. El agente de IA consulta a través del protocolo **MCP** las herramientas de validación de sintomatología odontológica y guías clínicas para estructurar el diagnóstico sugerido.

---

## 3. Catálogo Previsto de Herramientas (Tools) y Recursos (Resources)

### A. Herramientas (MCP Tools):
- `validar_nomenclatura_dental`:
  - Valida si las piezas dentales mencionadas en la nota médica corresponden al esquema FDI válido (11 a 48, o 51 a 85 en dentición temporal).
- `detectar_contraindicacion_medicamento`:
  - Recibe el medicamento prescrito previsto y los antecedentes médicos del paciente (ej: alergias a penicilinas, hipertensión) y advierte riesgos potenciales.
- `generar_resumen_evolucion`:
  - Estructura las notas libres del dentista bajo el formato SOAP (Subjetivo, Objetivo, Análisis, Plan).

### B. Recursos (MCP Resources):
- `odontoclinic://guias/restauraciones`: Guía clínica estandarizada de procedimientos de operatoria dental.
- `odontoclinic://nomenclatura/fdi`: Catálogo estandarizado de piezas dentales según la Federación Dental Internacional.

---

## 4. Futura Configuración del Servidor MCP

Cuando se autorice la implementación del servidor:
- **Tecnología recomendada:** Node.js / TypeScript con `@modelcontextprotocol/sdk` o Python FastMCP.
- **Modos de Transporte admitidos:**
  - `stdio`: Para subprocesos locales acoplados al agente de IA.
  - `SSE (Server-Sent Events)`: Para comunicación HTTP local sobre el puerto reservado `3100`.
- **Variables de Entorno previstas (`mcp/server/.env`):**
  ```env
  MCP_SERVER_NAME=odontoclinic-mcp-clinical-context
  MCP_PORT=3100
  MCP_TRANSPORT=sse
  MS2_SERVICE_URL=http://localhost/api/expediente
  ANONYMIZE_PATIENT_DATA=true
  ```

---

## 5. Estado de Implementación

- [x] Definición conceptual, catálogo de tools y recursos documentado.
- [ ] Inicialización del servidor de código en `mcp/server` (Pendiente de autorización).
- [ ] Integración con el motor LLM de `ms2-clinico-ia`.
