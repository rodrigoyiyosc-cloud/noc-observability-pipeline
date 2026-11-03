# Simulacro a ciegas para el webhook en dev (PowerShell 5.1)
# Uso: powershell -NoProfile -ExecutionPolicy Bypass -File .\falla-ciega.ps1 -Accion Inyectar|Revelar|Restaurar
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Inyectar", "Revelar", "Restaurar")]
    [string]$Accion
)

$ns  = "dev"
$d   = "webhook-service"
$c   = "webhook-receiver"
$img = "noc-webhook-service:v1.0.12"
$estado = Join-Path $env:TEMP "falla_ciega.dat"

function Mark($m) {
    "$(Get-Date -Format 'HH:mm:ss')  $m" | Tee-Object -FilePath .\timeline.txt -Append | Out-Null
}

switch ($Accion) {

    "Inyectar" {
        $n = Get-Random -InputObject @(1, 2, 3, 4, 5)
        [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("$n")) | Set-Content $estado

        switch ($n) {
            1 { kubectl set image deployment/$d $c=noc-webhook-service:v9.9.9 -n $ns | Out-Null }
            2 { kubectl set env deployment/$d NOC_WEBHOOK_TOKEN= -n $ns | Out-Null }
            3 { docker stop timescaledb | Out-Null }
            4 { kubectl set resources deployment/$d -n $ns --requests=memory=10Mi --limits=memory=20Mi | Out-Null }
            5 { kubectl set env deployment/$d PG_HOST=host-falso -n $ns | Out-Null }
        }

        Mark "INYECTO falla ciega"
        Write-Host ""
        Write-Host "Falla inyectada. Cronometro en marcha ($(Get-Date -Format 'HH:mm:ss'))."
        Write-Host "Diagnostica sin usar esta herramienta."
    }

    "Revelar" {
        if (-not (Test-Path $estado)) { Write-Host "No hay falla registrada."; return }
        $n = [int]([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String((Get-Content $estado))))
        $nombres = @{
            1 = "Imagen inexistente (ImagePullBackOff)"
            2 = "NOC_WEBHOOK_TOKEN vacio (CrashLoopBackOff)"
            3 = "Postgres detenido (pod 0/1, /ready 503)"
            4 = "Limite de memoria 20Mi (OOMKilled)"
            5 = "PG_HOST erroneo (pod 0/1, /ready 503)"
        }
        Write-Host "La falla era: $($nombres[$n])"
    }

    "Restaurar" {
        docker start timescaledb | Out-Null
        kubectl set image deployment/$d $c=$img -n $ns | Out-Null
        kubectl set env deployment/$d NOC_WEBHOOK_TOKEN- PG_HOST- -n $ns | Out-Null
        kubectl set resources deployment/$d -n $ns --requests=cpu=100m,memory=256Mi --limits=cpu=500m,memory=512Mi | Out-Null
        kubectl rollout status deployment/$d -n $ns --timeout=120s
        Remove-Item $estado -ErrorAction SilentlyContinue
        Mark "RESTAURADO: laboratorio al estado base"
        kubectl get pods -n $ns -l app.kubernetes.io/name=webhook-receiver
    }
}
