<#
.SYNOPSIS
    Comprueba el estado de los puertos de red del ecosistema local de microservicios.
.DESCRIPTION
    Inspecciona los puertos 80 (Gateway Nginx), 8081 (MS1 Seguridad), 3001 (MS2 Expediente)
    y 8001 (MS3 Agendamiento) para determinar si los servicios están en escucha y qué proceso los posee.
#>

$servicios = @(
    [PSCustomObject]@{
        Puerto = 80
        Servicio = "API Gateway (Nginx)"
        Responsable = "Infraestructura Compartida"
        Prefijo = "/"
    },
    [PSCustomObject]@{
        Puerto = 8081
        Servicio = "MS1 Seguridad (Spring Boot)"
        Responsable = "Dennis"
        Prefijo = "/api/seguridad"
    },
    [PSCustomObject]@{
        Puerto = 3001
        Servicio = "MS2 Expediente Clínico (NestJS)"
        Responsable = "Henry"
        Prefijo = "/api/expediente"
    },
    [PSCustomObject]@{
        Puerto = 8001
        Servicio = "MS3 Agendamiento (Laravel)"
        Responsable = "Wendy"
        Prefijo = "/api/agendamiento"
    }
)

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "  DIAGNÓSTICO DE PUERTOS LOCALES - PLATFORM INFRASTRUCTURE" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan

$resultados = @()

foreach ($item in $servicios) {
    $puerto = $item.Puerto
    $conexion = Get-NetTCPConnection -LocalPort $puerto -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1

    if ($conexion) {
        $pidProceso = $conexion.OwningProcess
        $proceso = Get-Process -Id $pidProceso -ErrorAction SilentlyContinue
        $nombreProceso = if ($proceso) { $proceso.ProcessName } else { "PID: $pidProceso" }

        $resultados += [PSCustomObject]@{
            Puerto      = $puerto
            Estado      = "EN ESCUCHA"
            Servicio    = $item.Servicio
            Responsable = $item.Responsable
            PID         = $pidProceso
            Proceso     = $nombreProceso
        }
    } else {
        $resultados += [PSCustomObject]@{
            Puerto      = $puerto
            Estado      = "APAGADO / LIBRE"
            Servicio    = $item.Servicio
            Responsable = $item.Responsable
            PID         = "-"
            Proceso     = "-"
        }
    }
}

$resultados | Format-Table -AutoSize -Property Puerto, Estado, Servicio, Responsable, PID, Proceso

Write-Host "`nResumen:" -ForegroundColor Yellow
foreach ($r in $resultados) {
    if ($r.Estado -eq "EN ESCUCHA") {
        Write-Host "  [OK] Puerto $($r.Puerto) ($($r.Servicio)): Activo en PID $($r.PID) ($($r.Proceso))" -ForegroundColor Green
    } else {
        Write-Host "  [--] Puerto $($r.Puerto) ($($r.Servicio)): Inactivo o no iniciado" -ForegroundColor DarkGray
    }
}
Write-Host "=================================================================`n" -ForegroundColor Cyan
