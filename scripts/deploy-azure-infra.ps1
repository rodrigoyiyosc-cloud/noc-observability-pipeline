<#
    deploy-azure-infra.ps1
    Aprovisiona la infraestructura base en Azure (RG + ACR + AKS) para la
    Fase 2 del webhook-service. Ejecutar una sola vez (o cuando cambie la
    infra); el despliegue de la app va por ci.yml (job deploy-to-aks).

    Uso:
        ./deploy-azure-infra.ps1
#>

$ErrorActionPreference = "Stop"

# ── Variables — ajustar antes de correr ─────────────────────────────────────
$SUBSCRIPTION_ID  = "8168dd9c-6e5f-4c49-825c-c126f08f2c7e"
$RESOURCE_GROUP   = "noc-telemetria-rg"
$LOCATION         = "eastus"
$ACR_NAME         = "nocacr"              # debe coincidir con nocacr.azurecr.io usado en k8s/ y ci.yml
$AKS_CLUSTER_NAME = "noc-aks-cluster"
$AKS_NODE_COUNT   = 2
$AKS_NODE_VM_SIZE = "Standard_D2as_v7"

# ── 1. Login ─────────────────────────────────────────────────────────────
az login
az account set --subscription $SUBSCRIPTION_ID

# ── 2. Resource Group ────────────────────────────────────────────────────
az group create `
    --name $RESOURCE_GROUP `
    --location $LOCATION

# ── 3. Azure Container Registry ─────────────────────────────────────────
az acr create `
    --resource-group $RESOURCE_GROUP `
    --name $ACR_NAME `
    --sku Basic `
    --admin-enabled true

# ── 4. AKS Cluster ───────────────────────────────────────────────────────
az aks create `
    --resource-group $RESOURCE_GROUP `
    --name $AKS_CLUSTER_NAME `
    --node-count $AKS_NODE_COUNT `
    --node-vm-size $AKS_NODE_VM_SIZE `
    --generate-ssh-keys

# ── 5. Vincular ACR al AKS (pull de imágenes sin imagePullSecrets) ──────
az aks update `
    --resource-group $RESOURCE_GROUP `
    --name $AKS_CLUSTER_NAME `
    --attach-acr $ACR_NAME

# ── 6. Credenciales locales de kubectl ───────────────────────────────────
az aks get-credentials `
    --resource-group $RESOURCE_GROUP `
    --name $AKS_CLUSTER_NAME `
    --overwrite-existing

Write-Host "Infra lista: RG=$RESOURCE_GROUP ACR=$ACR_NAME AKS=$AKS_CLUSTER_NAME"
