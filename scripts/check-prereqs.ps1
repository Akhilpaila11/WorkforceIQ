# WorkforceIQ - prerequisite check (Windows PowerShell 5.1+)
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\check-prereqs.ps1
# Prints the version of every required tool and exits with code 1 if one is missing.

$ErrorActionPreference = 'Continue'
$missing = @()

function Show-Tool {
    param([string]$Label, [string]$Command, [string[]]$VersionArgs, [string]$Hint)
    $cmd = Get-Command $Command -ErrorAction SilentlyContinue
    if ($null -eq $cmd) {
        Write-Host ("[MISSING] {0,-12} {1}" -f $Label, $Hint) -ForegroundColor Yellow
        return $false
    }
    $version = (& $Command @VersionArgs 2>&1 | Select-Object -First 1)
    Write-Host ("[OK]      {0,-12} {1}" -f $Label, $version) -ForegroundColor Green
    return $true
}

if (-not (Show-Tool 'Python 3.12+' 'py' @('-3.13', '--version') 'Install Python 3.12 or 3.13 from python.org')) { $missing += 'python' }
if (-not (Show-Tool 'Node.js' 'node' @('--version') 'Install Node.js 20+ (winget install OpenJS.NodeJS.LTS)')) { $missing += 'node' }
if (-not (Show-Tool 'npm' 'npm' @('--version') 'Comes with Node.js')) { $missing += 'npm' }
if (-not (Show-Tool 'git' 'git' @('--version') 'winget install Git.Git')) { $missing += 'git' }

$psql = Get-Command psql -ErrorAction SilentlyContinue
if ($null -eq $psql) {
    $candidate = Get-ChildItem 'C:\Program Files\PostgreSQL\*\bin\psql.exe' -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1
    if ($candidate) {
        Write-Host ("[OK]      {0,-12} {1} (not on PATH: add {2})" -f 'PostgreSQL', (& $candidate.FullName --version), $candidate.DirectoryName) -ForegroundColor Green
    } else {
        # Optional: SQLite is the default database (decision A-35).
        Write-Host ("[OPTIONAL] {0,-11} {1}" -f 'PostgreSQL', 'not installed - SQLite is used by default (see README)') -ForegroundColor Cyan
    }
} else {
    Write-Host ("[OK]      {0,-12} {1}" -f 'PostgreSQL', (& psql --version)) -ForegroundColor Green
}

$port = Test-NetConnection -ComputerName localhost -Port 5432 -InformationLevel Quiet -WarningAction SilentlyContinue
Write-Host ("[{0}] PostgreSQL listening on localhost:5432" -f $(if ($port) { 'OK     ' } else { 'NO     ' }))

if ($missing.Count -gt 0) {
    Write-Host "Missing: $($missing -join ', ')" -ForegroundColor Yellow
    exit 1
}
Write-Host 'All prerequisites found.' -ForegroundColor Green
exit 0
