<#
.SYNOPSIS
    Ejecuta las pruebas aisladas de transporte HTTP con Nginx real.
.DESCRIPTION
    Requiere Python 3, Docker y la imagen local nginx:1.28-alpine.
    No descarga imágenes ni usa servicios compartidos. No certifica JWT,
    idempotencia del backend, MCP real ni PagoFácil. Un 502 no es éxito.
    Reenvía argumentos como --help, --baseline-config y --legacy-only.
#>
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RunnerArgs
)

$ErrorActionPreference = "Stop"
try {
    $runner = Join-Path $PSScriptRoot "test_gateway.py"
    & python $runner @RunnerArgs
    $result = $LASTEXITCODE
    if ($result -ne 0) {
        Write-Host "[ERROR] La verificación falló (exit $result)." -ForegroundColor Red
    }
    exit $result
} catch {
    Write-Host "[ERROR] No se pudo ejecutar la verificación: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
