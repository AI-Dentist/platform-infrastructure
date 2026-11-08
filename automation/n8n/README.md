# n8n: alertas de cobranza por WhatsApp

MS1 (ERP) envía alertas de cobranza a un webhook de n8n desde la herramienta MCP
`dispararAlertaCobranzaWhatsapp` y el modo "Monitorea mi negocio". Este directorio
trae un n8n local y el workflow que recibe esa alerta y la envía por la API de
WhatsApp Business Cloud.

## Levantar

```powershell
$env:ERP_WEBHOOK_SECRET = "<secreto-local>"       # el mismo valor en MS1
$env:WHATSAPP_PHONE_NUMBER_ID = "<id>"            # opcional: sin él no se envía
$env:WHATSAPP_ACCESS_TOKEN = "<token>"            # opcional: nunca en Git
docker compose -f automation/n8n/docker-compose.yml up -d
docker compose -f automation/n8n/docker-compose.yml exec n8n n8n import:workflow --input=/workflows/cobranza-whatsapp.json
```

Abrir `http://localhost:5678`, activar el workflow "ERP - Alerta de cobranza por
WhatsApp". La URL de producción del webhook es
`http://localhost:5678/webhook/erp-cobranza`.

## Configurar MS1

| Variable | Valor local |
|---|---|
| `N8N_ENABLED` | `true` |
| `N8N_WEBHOOK_URL` | `http://localhost:5678/webhook/erp-cobranza` |
| `N8N_WEBHOOK_SECRET` | igual a `ERP_WEBHOOK_SECRET` (cabecera `X-ERP-Webhook-Secret`) |

## Contrato

`POST /webhook/erp-cobranza` con cabecera `X-ERP-Webhook-Secret` y cuerpo JSON:

```json
{ "pacienteNombre": "Ana Rojas", "telefono": "59170000000", "montoBs": 350.00,
  "concepto": "Cuota 2 de 4 - Ortodoncia", "fechaVencimiento": "2026-11-15" }
```

| Respuesta | Significado |
|---|---|
| `200 {"enviado": true, "canal": "whatsapp"}` | Meta aceptó el mensaje |
| `401 {"enviado": false, "motivo": "SOLICITUD_RECHAZADA"}` | Secreto inválido o teléfono vacío |
| Error/timeout de n8n o de Meta | MS1 informa la alerta como no enviada; no reintenta en silencio |

Si n8n no está levantado, MS1 responde con su resultado seguro de "no enviado".
Las pruebas `scripts/tests/test_n8n_workflow.py` validan la estructura del
workflow y del compose; no prueban el envío real a WhatsApp.
