
git add .gitignore$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$frontendRoot = Join-Path $projectRoot "frontend"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$apiUrl = "http://127.0.0.1:8000"
$frontendUrl = "http://127.0.0.1:5173"

function Test-HttpEndpoint {
    param(
        [string]$Uri,
        [string]$ExpectedStatus
    )

    try {
        $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 3
        if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) {
            return $false
        }
        if ($ExpectedStatus -eq "ok") {
            $payload = $response.Content | ConvertFrom-Json
            return $payload.status -eq "ok"
        }
        return $true
    }
    catch {
        return $false
    }
}

function Test-TcpPort {
    param([int]$Port)

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $connect = $client.ConnectAsync("127.0.0.1", $Port)
        return $connect.Wait(1000) -and $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Start-ServiceConsole {
    param(
        [string]$Title,
        [string]$Command
    )

    $safeRoot = $projectRoot.Replace("'", "''")
    $consoleCommand = "`$Host.UI.RawUI.WindowTitle = '$Title'; Set-Location -LiteralPath '$safeRoot'; $Command"
    Start-Process -FilePath (Join-Path $PSHOME "powershell.exe") -ArgumentList @(
        "-NoExit",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        $consoleCommand
    ) | Out-Null
}

if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot "package.json"))) {
    throw "Frontend package.json was not found in '$frontendRoot'."
}
if (-not (Get-Command node.exe -ErrorAction SilentlyContinue)) {
    throw "Node.js is required. Install Node.js 18 or newer, then run this script again."
}
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw "npm was not found. Reinstall Node.js with npm included, then run this script again."
}

$nodeVersion = (& node.exe --version).TrimStart("v")
$nodeMajor = [int]($nodeVersion.Split(".")[0])
if ($nodeMajor -lt 18) {
    throw "Node.js 18 or newer is required; found $nodeVersion."
}

if (-not (Test-Path -LiteralPath $python)) {
    $setupScript = Join-Path $projectRoot "setup.ps1"
    if (-not (Test-Path -LiteralPath $setupScript)) {
        throw "Project Python environment is missing and setup.ps1 was not found."
    }
    Write-Host "Project Python environment not found. Running setup.ps1..."
    & (Join-Path $PSHOME "powershell.exe") -NoProfile -ExecutionPolicy Bypass -File $setupScript
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $python)) {
        throw "Python setup did not complete successfully. Resolve the setup error and retry."
    }
}

Push-Location $projectRoot
try {
    & $python -c "import fastapi, uvicorn; import app.api"
    if ($LASTEXITCODE -ne 0) {
        throw "The project Python environment is missing API dependencies. Run .\setup.ps1 and try again."
    }
}
finally {
    Pop-Location
}

$viteEntry = Join-Path $frontendRoot "node_modules\vite\bin\vite.js"
if (-not (Test-Path -LiteralPath $viteEntry)) {
    Write-Host "Installing frontend dependencies with npm ci..."
    Push-Location $frontendRoot
    try {
        & npm.cmd ci
        if ($LASTEXITCODE -ne 0) {
            throw "npm ci failed. Review the npm output and retry."
        }
    }
    finally {
        Pop-Location
    }
}

if (-not (Test-HttpEndpoint -Uri "$apiUrl/health" -ExpectedStatus "ok")) {
    if (Test-TcpPort -Port 8000) {
        throw "Port 8000 is occupied, but $apiUrl/health did not return status=ok. Close the conflicting process or configure another port."
    }
    Write-Host "Starting FastAPI in a new PowerShell window..."
    Start-ServiceConsole -Title "Contract Observatory - API" -Command "& '$python' -m uvicorn app.api:app --host 127.0.0.1 --port 8000"
}
else {
    Write-Host "FastAPI is already healthy at $apiUrl."
}

if (-not (Test-HttpEndpoint -Uri $frontendUrl -ExpectedStatus "any")) {
    if (Test-TcpPort -Port 5173) {
        throw "Port 5173 is occupied, but Vite is not responding at $frontendUrl. Close the conflicting process or configure another port."
    }
    Write-Host "Starting Vite in a new PowerShell window..."
    $safeFrontend = $frontendRoot.Replace("'", "''")
    Start-ServiceConsole -Title "Contract Observatory - Frontend" -Command "Set-Location -LiteralPath '$safeFrontend'; npm.cmd run dev -- --host 127.0.0.1 --port 5173 --strictPort"
}
else {
    Write-Host "Frontend is already responding at $frontendUrl."
}

$deadline = (Get-Date).AddSeconds(45)
do {
    $apiReady = Test-HttpEndpoint -Uri "$apiUrl/health" -ExpectedStatus "ok"
    $frontendReady = Test-HttpEndpoint -Uri $frontendUrl -ExpectedStatus "any"
    if ($apiReady -and $frontendReady) {
        break
    }
    Start-Sleep -Seconds 1
} while ((Get-Date) -lt $deadline)

if (-not $apiReady) {
    throw "FastAPI did not become healthy at $apiUrl/health. Check the API PowerShell window for the startup error."
}
if (-not $frontendReady) {
    throw "Vite did not respond at $frontendUrl. Check the frontend PowerShell window for the startup error."
}

Write-Host ""
Write-Host "Contract Observatory is ready."
Write-Host "Frontend: $frontendUrl"
Write-Host "API health: $apiUrl/health"
Write-Host "API docs: $apiUrl/docs"
Write-Host "Keep both service windows open. Press Ctrl+C in each window to stop its service."
Start-Process $frontendUrl
