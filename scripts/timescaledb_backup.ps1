<#
.SYNOPSIS
  Backup, restauracion y prueba de restauracion de TimescaleDB (docker-compose, contenedor "timescaledb").

.EXAMPLE
  .\scripts\timescaledb_backup.ps1 all
  .\scripts\timescaledb_backup.ps1 backup
  .\scripts\timescaledb_backup.ps1 verify
  .\scripts\timescaledb_backup.ps1 verify -File .\backups\noc_20261006_120000.dump
  .\scripts\timescaledb_backup.ps1 restore -File .\backups\noc_20261006_120000.dump -Target noc_restored
  .\scripts\timescaledb_backup.ps1 prune -RetentionDays 7

  Credenciales: PG_USER / PG_DB / PG_PASSWORD desde variables de entorno o desde .env en la raiz del repo.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('backup', 'verify', 'restore', 'prune', 'all')]
    [string]$Action,
    [string]$File,
    [string]$Target,
    [string]$Container = 'timescaledb',
    [string]$BackupDir,
    [int]$RetentionDays = 7
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not $BackupDir) { $BackupDir = Join-Path $RepoRoot 'backups' }

# ---------------------------------------------------------------- utilidades
function Write-Log {
    param([string]$Level, [string]$Message)
    $color = switch ($Level) { 'ERROR' { 'Red' } 'WARN' { 'Yellow' } 'OK' { 'Green' } default { 'Gray' } }
    Write-Host ("{0} [{1}] {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message) -ForegroundColor $color
}

function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return }
    foreach ($line in Get-Content -Path $Path) {
        if ($line -match '^\s*#' -or $line -notmatch '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') { continue }
        $key = $Matches[1]
        $val = $Matches[2].Trim('"').Trim("'")
        if (-not [Environment]::GetEnvironmentVariable($key, 'Process')) {
            [Environment]::SetEnvironmentVariable($key, $val, 'Process')
        }
    }
}

Import-DotEnv -Path (Join-Path $RepoRoot '.env')

$PgUser     = if ($env:PG_USER) { $env:PG_USER } else { 'noc_user' }
$PgDb       = if ($env:PG_DB) { $env:PG_DB } else { 'noc' }
$PgPassword = $env:PG_PASSWORD
if (-not $PgPassword) { throw 'Falta PG_PASSWORD (definelo en .env o con $env:PG_PASSWORD).' }

# Tablas a comparar entre origen y restauracion (columna de tiempo para el corte)
$CheckTables = @(
    @{ T = 'network_telemetry'; C = 'ts' },
    @{ T = 'incident_logs';     C = 'received_at' },
    @{ T = 'devices';           C = $null }
)

function Invoke-Docker {
    param([string[]]$DockerArgs, [switch]$AllowFail)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'   # evita que el stderr de docker/pg_restore aborte en PS 5.1
    try {
        $out  = & docker @DockerArgs 2>&1 | ForEach-Object { "$_" }
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $prev }
    $text = ($out -join "`n")
    if ($code -ne 0 -and -not $AllowFail) {
        $safe = ("docker " + ($DockerArgs -join ' ') + " fallo (codigo $code): $text").Replace($PgPassword, '***')
        throw $safe
    }
    return [pscustomobject]@{ Code = $code; Output = $text }
}

function Invoke-InContainer {
    param([string[]]$Cmd, [switch]$AllowFail)
    $dockerArgs = @('exec', '-e', "PGPASSWORD=$PgPassword", $Container) + $Cmd
    return Invoke-Docker -DockerArgs $dockerArgs -AllowFail:$AllowFail
}

function Invoke-Psql {
    param([string]$Db, [string]$Sql)
    $r = Invoke-InContainer -Cmd @('psql', '-U', $PgUser, '-d', $Db, '-v', 'ON_ERROR_STOP=1', '-X', '-At', '-c', $Sql)
    return $r.Output.Trim()
}

function Assert-Prereqs {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'docker no esta instalado o no esta en el PATH.' }
    $r = Invoke-Docker -DockerArgs @('inspect', '-f', '{{.State.Running}}', $Container) -AllowFail
    if ($r.Code -ne 0 -or $r.Output.Trim() -ne 'true') {
        throw "El contenedor '$Container' no esta corriendo. Ejecuta: docker compose up -d timescaledb"
    }
    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
}

function Get-Counts {
    param([string]$Db, [string]$Cutoff)
    $res = [ordered]@{}
    foreach ($t in $CheckTables) {
        $where = ''
        if ($t.C) { $where = "WHERE $($t.C) < '$Cutoff'::timestamptz" }
        $res[$t.T] = [int64](Invoke-Psql $Db "SELECT count(*) FROM $($t.T) $where;")
    }
    return $res
}

# -------------------------------------------------------------------- backup
function New-Backup {
    Assert-Prereqs
    $stamp  = Get-Date -Format 'yyyyMMdd_HHmmss'
    $name   = "${PgDb}_$stamp.dump"
    $local  = Join-Path $BackupDir $name
    $remote = "/tmp/$name"

    # Corte 1 minuto atras: filas ya consolidadas (el simulador sigue insertando)
    $cutoff = Invoke-Psql $PgDb "SELECT (now() - interval '1 minute')::text;"

    Write-Log 'INFO' "Iniciando backup de '$PgDb' -> $local"
    # El dump se hace DENTRO del contenedor y se copia con docker cp:
    # el pipeline de PowerShell corrompe datos binarios (formato -Fc).
    Invoke-InContainer -Cmd @('pg_dump', '-U', $PgUser, '-d', $PgDb, '-Fc', '--no-owner', '-f', $remote) | Out-Null
    try {
        Invoke-InContainer -Cmd @('pg_restore', '--list', $remote) | Out-Null   # el dump debe ser legible
        Invoke-Docker -DockerArgs @('cp', "${Container}:$remote", $local) | Out-Null
    }
    finally {
        Invoke-InContainer -Cmd @('rm', '-f', $remote) -AllowFail | Out-Null
    }

    if (-not (Test-Path $local) -or (Get-Item $local).Length -eq 0) { throw 'El dump quedo vacio o no se copio.' }

    $hash = (Get-FileHash -Algorithm SHA256 -Path $local).Hash.ToLower()
    Set-Content -Path "$local.sha256" -Value "$hash  $name" -Encoding ASCII

    $manifest = @("cutoff=$cutoff")
    $counts = Get-Counts $PgDb $cutoff
    foreach ($k in $counts.Keys) { $manifest += "$k=$($counts[$k])" }
    Set-Content -Path "$local.manifest" -Value $manifest -Encoding ASCII

    $sizeMb = [math]::Round((Get-Item $local).Length / 1MB, 2)
    Write-Log 'OK' "Backup OK ($sizeMb MB) con checksum y manifiesto."
    return $local
}

# ------------------------------------------------------ restauracion en BD nueva
function Restore-IntoDb {
    param([string]$Dump, [string]$TargetDb)

    if (-not (Test-Path $Dump)) { throw "No existe el archivo: $Dump" }
    if ($TargetDb -notmatch '^[a-z_][a-z0-9_]*$') { throw "Nombre de BD invalido: '$TargetDb' (usa minusculas, numeros y _)." }
    $Dump = (Resolve-Path $Dump).Path

    $shaFile = "$Dump.sha256"
    if (Test-Path $shaFile) {
        $expected = ((Get-Content $shaFile -TotalCount 1) -split '\s+')[0].ToLower()
        $actual   = (Get-FileHash -Algorithm SHA256 -Path $Dump).Hash.ToLower()
        if ($expected -ne $actual) { throw 'Checksum invalido: el backup esta corrupto.' }
        Write-Log 'INFO' 'Checksum verificado.'
    }

    if ((Invoke-Psql 'postgres' "SELECT 1 FROM pg_database WHERE datname='$TargetDb';") -eq '1') {
        throw "La BD destino '$TargetDb' ya existe; elige otro nombre."
    }

    Write-Log 'INFO' "Creando BD '$TargetDb' con extension timescaledb"
    Invoke-Psql 'postgres' "CREATE DATABASE $TargetDb;" | Out-Null
    Invoke-Psql $TargetDb 'CREATE EXTENSION IF NOT EXISTS timescaledb;' | Out-Null

    $remote = "/tmp/restore_$TargetDb.dump"
    Invoke-Docker -DockerArgs @('cp', $Dump, "${Container}:$remote") | Out-Null
    try {
        Write-Log 'INFO' 'Restaurando (pre_restore -> pg_restore -> post_restore)'
        Invoke-Psql $TargetDb 'SELECT timescaledb_pre_restore();' | Out-Null
        $r = Invoke-InContainer -Cmd @('pg_restore', '-U', $PgUser, '-d', $TargetDb, '--no-owner', $remote) -AllowFail
        if ($r.Code -ne 0) { Write-Log 'WARN' 'pg_restore termino con avisos (p. ej. extension ya creada); la verificacion de conteos decide.' }
        Invoke-Psql $TargetDb 'SELECT timescaledb_post_restore();' | Out-Null
    }
    finally {
        Invoke-InContainer -Cmd @('rm', '-f', $remote) -AllowFail | Out-Null
    }
    Write-Log 'INFO' "Restauracion completada en '$TargetDb'."
}

function Restore-Backup {
    Assert-Prereqs
    if (-not $File) { throw 'Uso: .\scripts\timescaledb_backup.ps1 restore -File <archivo.dump> [-Target <bd_destino>]' }
    $dest = if ($Target) { $Target } else { "${PgDb}_restored_$(Get-Date -Format 'yyyyMMdd_HHmmss')" }
    Restore-IntoDb -Dump $File -TargetDb $dest
    Write-Log 'OK' "Revisa '$dest'. No se sobrescribio '$PgDb'."
}

# ------------------------------------------------------- prueba de restauracion
function Test-Backup {
    param([string]$Dump)
    Assert-Prereqs

    if (-not $Dump) {
        $latest = Get-ChildItem -Path $BackupDir -Filter "${PgDb}_*.dump" -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if (-not $latest) { throw "No hay backups que verificar en $BackupDir" }
        $Dump = $latest.FullName
    }
    $manifestPath = "$Dump.manifest"
    if (-not (Test-Path $manifestPath)) { throw "Falta el manifiesto: $manifestPath" }

    $temp = "restore_test_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
    Write-Log 'INFO' "Prueba de restauracion de $(Split-Path $Dump -Leaf) en '$temp'"

    $failed = $false
    try {
        Restore-IntoDb -Dump $Dump -TargetDb $temp

        $expected = [ordered]@{}
        $cutoff = $null
        foreach ($line in Get-Content $manifestPath) {
            $k, $v = $line -split '=', 2
            if ($k -eq 'cutoff') { $cutoff = $v } elseif ($k) { $expected[$k] = [int64]$v }
        }
        if (-not $cutoff) { throw 'El manifiesto no tiene cutoff.' }

        $actual = Get-Counts $temp $cutoff
        foreach ($k in $expected.Keys) {
            if ($actual[$k] -eq $expected[$k]) {
                Write-Log 'OK' "OK    ${k}: $($actual[$k]) filas (esperadas $($expected[$k]))"
            }
            else {
                Write-Log 'ERROR' "FALLA ${k}: restauradas $($actual[$k]), esperadas $($expected[$k])"
                $failed = $true
            }
        }

        $ht = Invoke-Psql $temp "SELECT count(*) FROM timescaledb_information.hypertables WHERE hypertable_name='network_telemetry';"
        if ($ht -eq '1') { Write-Log 'OK' 'OK    network_telemetry sigue siendo hypertable' }
        else { Write-Log 'ERROR' 'FALLA network_telemetry no quedo como hypertable'; $failed = $true }
    }
    finally {
        try {
            Invoke-Psql 'postgres' "DROP DATABASE IF EXISTS $temp WITH (FORCE);" | Out-Null
            Write-Log 'INFO' "BD temporal '$temp' eliminada"
        }
        catch { Write-Log 'WARN' "No se pudo eliminar la BD temporal '$temp': $($_.Exception.Message)" }
    }

    if ($failed) { throw "Prueba de restauracion FALLIDA para $(Split-Path $Dump -Leaf)" }
    Write-Log 'OK' "Prueba de restauracion EXITOSA para $(Split-Path $Dump -Leaf)"
}

# --------------------------------------------------------------------- prune
function Remove-OldBackups {
    if (-not (Test-Path $BackupDir)) { return }
    $limit = (Get-Date).AddDays(-$RetentionDays)
    Write-Log 'INFO' "Eliminando backups con mas de $RetentionDays dias en $BackupDir"
    Get-ChildItem -Path $BackupDir -File |
        Where-Object { $_.Name -like "${PgDb}_*.dump*" -and $_.LastWriteTime -lt $limit } |
        ForEach-Object { Write-Log 'INFO' "Borrando $($_.Name)"; Remove-Item -Force $_.FullName }
}

# ---------------------------------------------------------------------- main
try {
    switch ($Action) {
        'backup'  { New-Backup | Out-Null }
        'verify'  { Test-Backup -Dump $File }
        'restore' { Restore-Backup }
        'prune'   { Remove-OldBackups }
        'all'     { $f = New-Backup; Test-Backup -Dump $f; Remove-OldBackups }
    }
}
catch {
    Write-Log 'ERROR' $_.Exception.Message
    exit 1
}