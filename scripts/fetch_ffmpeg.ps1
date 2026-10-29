# Descarga ffmpeg.exe para mux DASH (Atresplayer) vía Streamlink.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$PlayerDir = Join-Path $Root "player"
New-Item -ItemType Directory -Force -Path $PlayerDir | Out-Null
$Target = Join-Path $PlayerDir "ffmpeg.exe"

if (Test-Path $Target) {
    Write-Host "ffmpeg.exe ya existe en player\"
    exit 0
}

$Local = @(
    (Get-Command ffmpeg -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
    "C:\ffmpeg\bin\ffmpeg.exe",
    "C:\Program Files\ffmpeg\bin\ffmpeg.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

if ($Local) {
    Copy-Item $Local $Target -Force
    Write-Host "Copiado desde $Local"
    exit 0
}

Write-Host "Descargando ffmpeg essentials (GyanD)..."
$Api = "https://api.github.com/repos/GyanD/codexffmpeg/releases/latest"
$Rel = Invoke-RestMethod -Uri $Api -Headers @{ "User-Agent" = "TV-Win-CI" }
$Asset = $Rel.assets | Where-Object { $_.name -match "ffmpeg-.*-essentials_build\.zip$" } | Select-Object -First 1
if (-not $Asset) {
    throw "No se encontró ffmpeg essentials en la release latest"
}

$Tmp = Join-Path $env:TEMP ("tvwin-ffmpeg-" + [guid]::NewGuid())
New-Item -ItemType Directory -Force -Path $Tmp | Out-Null
$Archive = Join-Path $Tmp $Asset.name
Invoke-WebRequest -Uri $Asset.browser_download_url -OutFile $Archive -UseBasicParsing
$Extract = Join-Path $Tmp "out"
Expand-Archive -Path $Archive -DestinationPath $Extract -Force

$Found = Get-ChildItem -Path $Extract -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
if (-not $Found) {
    throw "ffmpeg.exe no apareció tras extraer el archivo"
}
Copy-Item $Found.FullName $Target -Force
Write-Host "ffmpeg listo: $Target ($([math]::Round((Get-Item $Target).Length/1MB)) MB)"
