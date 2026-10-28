# Descarga mpv.exe para embebido (CI / build local).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$PlayerDir = Join-Path $Root "player"
New-Item -ItemType Directory -Force -Path $PlayerDir | Out-Null
$Target = Join-Path $PlayerDir "mpv.exe"

if (Test-Path $Target) {
    Write-Host "mpv.exe ya existe en player\"
    exit 0
}

# Preferir instalación local si existe
$Local = @(
    "C:\Program Files\MPV Player\mpv.exe",
    "C:\Program Files\mpv\mpv.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($Local) {
    Copy-Item $Local $Target -Force
    Write-Host "Copiado desde $Local"
    exit 0
}

Write-Host "Descargando mpv (zhongfly/mpv-winbuild)..."
$Api = "https://api.github.com/repos/zhongfly/mpv-winbuild/releases/latest"
$Rel = Invoke-RestMethod -Uri $Api -Headers @{ "User-Agent" = "TV-Win-CI" }
$Asset = $Rel.assets | Where-Object { $_.name -match "mpv-x86_64-.*\.7z$" } | Select-Object -First 1
if (-not $Asset) {
    $Asset = $Rel.assets | Where-Object { $_.name -match "mpv-x86_64-.*\.zip$" } | Select-Object -First 1
}
if (-not $Asset) {
    throw "No se encontró asset mpv x86_64 en la release latest"
}

$Tmp = Join-Path $env:TEMP ("tvwin-mpv-" + [guid]::NewGuid())
New-Item -ItemType Directory -Force -Path $Tmp | Out-Null
$Archive = Join-Path $Tmp $Asset.name
Invoke-WebRequest -Uri $Asset.browser_download_url -OutFile $Archive -UseBasicParsing

$Extract = Join-Path $Tmp "out"
New-Item -ItemType Directory -Force -Path $Extract | Out-Null

if ($Archive -like "*.7z") {
    $Seven = @(
        "$env:ProgramFiles\7-Zip\7z.exe",
        "${env:ProgramFiles(x86)}\7-Zip\7z.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $Seven) {
        choco install 7zip -y --no-progress | Out-Null
        $Seven = "$env:ProgramFiles\7-Zip\7z.exe"
    }
    & $Seven x -y "-o$Extract" $Archive | Out-Null
} else {
    Expand-Archive -Path $Archive -DestinationPath $Extract -Force
}

$Found = Get-ChildItem -Path $Extract -Recurse -Filter "mpv.exe" | Select-Object -First 1
if (-not $Found) {
    throw "mpv.exe no apareció tras extraer el archivo"
}
Copy-Item $Found.FullName $Target -Force
Write-Host "mpv listo: $Target ($([math]::Round((Get-Item $Target).Length/1MB)) MB)"
