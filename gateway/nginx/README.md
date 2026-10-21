# Guía de Instalación y Ejecución de Nginx (API Gateway Local)

Esta guía describe cómo instalar, configurar y operar **Nginx en Windows** como API Gateway unificado para el sistema médico-odontológico distribuido.

---

## 1. Topología del Gateway y Microservicios

El Gateway centraliza las solicitudes del frontend en el puerto estándar `80` y las enruta por prefijo a cada microservicio local:

| Microservicio | Responsable | Tecnología | Puerto Local | Prefijo en Gateway (Puerto 80) | Estado Actual |
|---|---|---|---|---|---|
| **MS1 - Seguridad** | Dennis | Spring Boot | `8081` | `http://localhost/api/seguridad/` | En desarrollo |
| **MS2 - Expediente Clínico** | Henry | NestJS | `3001` | `http://localhost/api/expediente/` | Funcional (MongoDB) |
| **MS3 - Agendamiento** | Wendy | Laravel | `8001` | `http://localhost/api/agendamiento/` | En desarrollo |
| **Rutas no mapeadas** | N/A | Nginx Fallback | - | `http://localhost/*` | Retorna `404 Not Found` |

---

## 2. Requisitos Previos

- Sistema operativo **Windows 10 / 11**.
- PowerShell 5.1 o PowerShell 7+.
- Permisos de Administrador (para liberar el puerto 80 si otro servicio lo ocupa).
- Acceso al repositorio `platform-infrastructure` en la ruta local (ejemplo: `C:/2-2026/sw2/p2/platform-infrastructure`).

---

## 3. Instalación de Nginx en Windows

1. **Descarga**:
   - Descarga la versión estable de Nginx para Windows desde [nginx.org/en/download.html](https://nginx.org/en/download.html) (ejemplo: `nginx/Windows-1.24.x` o superior).
2. **Extracción en ruta estándar**:
   - Descomprime el contenido del archivo zip directamente en la raíz de tu disco C:
     ```
     C:\nginx\
     ├── conf\
     ├── contrib\
     ├── docs\
     ├── html\
     ├── logs\
     ├── temp\
     └── nginx.exe
     ```
   > **Importante:** La ruta recomendada y estandarizada para todo el equipo es `C:\nginx`.

---

## 4. Vinculación del Gateway al Repositorio

Para que no tengas que copiar archivos cada vez que haya cambios, enlazamos el archivo `gateway.conf` del repositorio directamente dentro de la configuración de Nginx.

1. Abre el archivo de configuración principal de Nginx:
   ```
   C:\nginx\conf\nginx.conf
   ```
2. Desactiva o comenta el bloque `server { ... }` que viene por defecto dentro de `http { ... }`.
3. Al final del bloque `http { ... }` (justo antes de la llave de cierre `}`), añade la directiva `include` apuntando a tu ruta del repositorio usando **barras inclinadas directas (`/`)**:

```nginx
http {
    include       mime.types;
    default_type  application/octet-stream;
    sendfile        on;
    keepalive_timeout  65;

    # Inclusión del Gateway del proyecto médico-odontológico
    include C:/2-2026/sw2/p2/platform-infrastructure/gateway/nginx/gateway.conf;
}
```

> **Nota crítica de sintaxis en Windows:** En Nginx se deben usar diagonales normales `/` (ej. `C:/ruta/archivo.conf`) y no diagonales invertidas `\`.

---

## 5. Ciclo de Vida y Comandos Operativos

Abre una consola de **PowerShell** en `C:\nginx`:

### A. Validar la sintaxis de la configuración (Obligatorio antes de iniciar o recargar)
```powershell
cd C:\nginx
.\nginx.exe -t
```
*Salida esperada:*
```text
nginx: the configuration file C:\nginx/conf/nginx.conf syntax is ok
nginx: configuration file C:\nginx/conf/nginx.conf test is successful
```

### B. Iniciar Nginx
```powershell
cd C:\nginx
start nginx
```
*Nota: `start nginx` inicia el proceso en segundo plano y te devuelve el control de la consola de inmediato.*

### C. Recargar cambios en caliente (Hot-Reload)
Si se actualiza `gateway.conf` o la configuración general, no es necesario reiniciar Nginx:
```powershell
cd C:\nginx
.\nginx.exe -s reload
```

### D. Detener Nginx
```powershell
# Detención rápida
cd C:\nginx
.\nginx.exe -s stop

# Detención ordenada (graceful shutdown)
cd C:\nginx
.\nginx.exe -s quit
```

### E. Comprobar si los procesos están activos
```powershell
Get-Process -Name nginx -ErrorAction SilentlyContinue
```

### F. Forzar terminación de procesos zombi (si no responde)
```powershell
Stop-Process -Name nginx -Force -ErrorAction SilentlyContinue
```

---

## 6. Scripts de Verificación Automatizada

Dentro de la carpeta `scripts/` de `platform-infrastructure` tienes a disposición dos scripts listos para usar:

### Diagnóstico de Puertos Locales
Verifica si el Gateway (80) y los microservicios (8081, 3001, 8001) están levantados y qué PID los tiene:
```powershell
cd C:\2-2026\sw2\p2\platform-infrastructure
.\scripts\check-ports.ps1
```

### Test de Conectividad End-to-End del Gateway
Ejecuta solicitudes a través de `http://localhost/...`:
```powershell
cd C:\2-2026\sw2\p2\platform-infrastructure
.\scripts\test-gateway.ps1
```

*Interpretación de resultados:*
- **200 OK**: El Gateway y el microservicio backend están funcionando y comunicándose.
- **502 Bad Gateway**: Nginx está funcionando bien en el puerto 80, pero el microservicio backend destino aún no ha sido iniciado en su puerto.
- **Error de red / Conexión rechazada al puerto 80**: Nginx no se ha iniciado. Ejecutar `start nginx` en `C:\nginx`.
- **404 Not Found en ruta no mapeada**: Regla de seguridad del Gateway funcionando correctamente.

---

## 7. Solución de Problemas Frecuentes en Windows

### 1. "El puerto 80 ya está en uso" (System PID 4 / IIS / W3SVC)
En Windows, el servicio IIS o el controlador `HTTP.sys` pueden adueñarse del puerto 80.
- Para verificar qué proceso usa el puerto 80:
  ```powershell
  Get-NetTCPConnection -LocalPort 80 -State Listen
  ```
- Si el PID es `4` (System), generalmente es el servicio de publicación web (IIS). Para detenerlo y deshabilitarlo temporalmente para desarrollo:
  ```powershell
  Stop-Service W3SVC -ErrorAction SilentlyContinue
  Set-Service W3SVC -StartupType Disabled -ErrorAction SilentlyContinue
  ```
- Si utilizas SQL Server Reporting Services o Web Deployment Service, revisa si tienen tomado el puerto 80.

### 2. Cambios en `gateway.conf` no surten efecto
- Asegúrate de ejecutar `.\nginx.exe -s reload` después de guardar cambios.
- Verifica en el Administrador de Tareas que no existan múltiples instancias residuales de `nginx.exe`. Si las hay, ejecuta `Stop-Process -Name nginx -Force` y luego `start nginx`.

### 3. Error `CreateFile() ... failed` en `error.log`
- Revisa `C:\nginx\logs\error.log`. Suele ocurrir si se usaron barras invertidas `\` en el `include` de `nginx.conf`. Cámbialas por `/`.
