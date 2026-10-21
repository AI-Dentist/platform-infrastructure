<#
.SYNOPSIS
    Prueba de conectividad y enrutamiento del API Gateway Nginx hacia los microservicios.
.DESCRIPTION
    Realiza peticiones HTTP a través del Gateway (puerto 80) hacia los prefijos configurados:
    - MS1: /api/seguridad/health  (Backend: 127.0.0.1:8081)
    - MS2: /api/expediente/health (Backend: 127.0.0.1:3001)
    - MS3: /api/agendamiento/health (Backend: 127.0.0.1:8001)
    - Ruta no mapeada: /api/desconocido (debe responder 404)
#>

$servicios = @(
    @{
        Nombre = "MS1 - Dennis (Seguridad - Spring Boot)"
        Url = "http://localhost/api/seguridad/health"
        PuertoBackend = 8081
    },
    @{
        Nombre = "MS2 - Henry (Expediente Clínico - NestJS)"
        Url = "http://localhost/api/expediente/health"
        PuertoBackend = 3001
    },
    @{
        Nombre = "MS3 - Wendy (Agendamiento - Laravel)"
        Url = "http://localhost/api/agendamiento/health"
        PuertoBackend = 8001
    }
)

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "  TEST DE CONECTIVIDAD DEL API GATEWAY (NGINX - PUERTO 80)" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan

# 1. Verificar si Nginx responde en la raíz
Write-Host "`n[1/2] Verificando estado general del Gateway Nginx..." -ForegroundColor Yellow
try {
    $reqGateway = Invoke-WebRequest -Uri "http://localhost/" -Method Head -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
    Write-Host "  [OK] Gateway Nginx responde (HTTP $($reqGateway.StatusCode))." -ForegroundColor Green
} catch {
    if ($_.Exception.Response) {
        $codigo = [int]$_.Exception.Response.StatusCode
        if ($codigo -eq 404) {
            Write-Host "  [OK] Gateway Nginx responde correctamente la regla 404 por defecto." -ForegroundColor Green
        } else {
            Write-Host "  [AVISO] Gateway respondió con HTTP $codigo" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  [ERROR CRÍTICO] No se puede conectar a Nginx en http://localhost:80." -ForegroundColor Red
        Write-Host "  Asegúrate de haber iniciado Nginx con 'start nginx' en C:\nginx." -ForegroundColor Red
        Write-Host "=================================================================`n" -ForegroundColor Cyan
        exit 1
    }
}

# 2. Probar rutas de microservicios
Write-Host "`n[2/2] Probando enrutamiento por prefijos de microservicios..." -ForegroundColor Yellow

foreach ($item in $servicios) {
    Write-Host "`n--> Evaluando $($item.Nombre)" -ForegroundColor White
    Write-Host "    URL Gateway : $($item.Url)" -ForegroundColor DarkGray
    Write-Host "    Target Local: 127.0.0.1:$($item.PuertoBackend)" -ForegroundColor DarkGray

    try {
        $response = Invoke-WebRequest -Uri $item.Url -Method Get -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        Write-Host "    [ONLINE] Conexión exitosa (HTTP $($response.StatusCode))" -ForegroundColor Green
        try {
            $json = $response.Content | ConvertFrom-Json
            Write-Host "    Respuesta:" -ForegroundColor DarkGreen
            $json | ConvertTo-Json -Depth 3 | Write-Host
        } catch {
            Write-Host "    Contenido: $($response.Content)" -ForegroundColor DarkGreen
        }
    }
    catch {
        if ($_.Exception.Response) {
            $codigo = [int]$_.Exception.Response.StatusCode
            if ($codigo -eq 502) {
                Write-Host "    [OFFLINE / 502 Bad Gateway] El Gateway enrutó correctamente, pero el backend local (puerto $($item.PuertoBackend)) no está iniciado." -ForegroundColor Yellow
            } elseif ($codigo -eq 404) {
                Write-Host "    [HTTP 404] Endpoint no encontrado en el Gateway o en el microservicio." -ForegroundColor DarkYellow
            } else {
                Write-Host "    [HTTP $codigo] $($_.Exception.Message)" -ForegroundColor Yellow
            }
        } else {
            Write-Host "    [ERROR DE RED] $($_.Exception.Message)" -ForegroundColor Red
        }
    }
}

# 3. Test de ruta no mapeada
Write-Host "`n--> Evaluando regla por defecto (Ruta no mapeada: http://localhost/api/desconocido)" -ForegroundColor White
try {
    $resInvalida = Invoke-WebRequest -Uri "http://localhost/api/desconocido" -Method Get -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
    Write-Host "    [AVISO] Se esperaba 404 pero devolvió HTTP $($resInvalida.StatusCode)" -ForegroundColor Yellow
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 404) {
        Write-Host "    [OK] Regla de fallback funcionando: devuelve 404 Not Found" -ForegroundColor Green
    } else {
        Write-Host "    Respuesta inesperada: $($_.Exception.Message)" -ForegroundColor DarkGray
    }
}

Write-Host "`n=================================================================" -ForegroundColor Cyan
Write-Host "  Fin de la prueba. Nota: 502 Bad Gateway es normal si el microservicio" -ForegroundColor Cyan
Write-Host "  respectivo todavía no se encuentra en ejecución." -ForegroundColor Cyan
Write-Host "=================================================================`n" -ForegroundColor Cyan
