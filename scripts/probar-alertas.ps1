# Token desde el .env (ejecuta esto en la carpeta del proyecto)
$env:NOC_WEBHOOK_TOKEN = ((Get-Content .env | Where-Object { $_ -match '^NOC_WEBHOOK_TOKEN=' }) -replace '^NOC_WEBHOOK_TOKEN=','').Trim('"')

$h = @{ Authorization = "Bearer $env:NOC_WEBHOOK_TOKEN" }

function Enviar($obj) {
  $json  = $obj | ConvertTo-Json -Depth 8
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
  try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/alert" -Method Post -Headers $h `
         -Body $bytes -ContentType "application/json; charset=utf-8"
    "HTTP $($r.StatusCode)"; $r.Content
  } catch {
    "HTTP $([int]$_.Exception.Response.StatusCode)"; $_.ErrorDetails.Message
  }
}