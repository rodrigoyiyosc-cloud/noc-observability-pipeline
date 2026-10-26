<#
.SYNOPSIS
    Aprovisiona un cluster local multinodo (1 control-plane, 2 workers) con kind.
#>
param (
    [string]$ClusterName = "noc-local-cluster"
)

Write-Host "Verificando dependencias..." -ForegroundColor Cyan
if (-not (Get-Command kind -ErrorAction SilentlyContinue)) {
    Write-Error "kind no está instalado o no se encuentra en el PATH."
    exit 1
}

if (-not (docker info --format '{{json .}}' 2>$null)) {
    Write-Error "Docker Desktop no está en ejecución. Inicia el motor e intenta nuevamente."
    exit 1
}

Write-Host "Creando clúster $ClusterName con topología de 3 nodos..." -ForegroundColor Cyan
kind create cluster --config "$PSScriptRoot/kind-3nodes.yaml"

Write-Host "Validando estado de los nodos..." -ForegroundColor Green
kubectl get nodes -o wide
