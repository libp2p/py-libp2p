#Requires -Version 5.1
<#
.SYNOPSIS
  Set up a py-libp2p development environment on Windows (native PowerShell).

.DESCRIPTION
  Selects a supported Python from pyproject.toml (classifiers intersect
  requires-python), checks cmake, prefers uv (>= 0.13.4) or pip (>= 26.2.2),
  then installs the dev dependency group.

  GMP is not required on Windows (fastecdsa is skipped on win32).

.PARAMETER Help
  Show help and exit.

.PARAMETER Python
  Force a Python version (e.g. 3.12). Must be in the supported set.

.PARAMETER Pip
  Force the pip install path even if uv is available.

.PARAMETER SkipPreCommit
  Do not run pre-commit install.

.EXAMPLE
  pwsh -File scripts\setup_dev.ps1

.EXAMPLE
  .\scripts\setup_dev.ps1 -Python 3.12
#>
[CmdletBinding()]
param(
    [Alias("h", "?")]
    [switch]$Help,

    [string]$Python = "",

    [switch]$Pip,

    [switch]$SkipPreCommit
)

$ErrorActionPreference = "Stop"

$MinUvVersion = [version]"0.13.4"
$MinPipVersion = [version]"26.2.2"

function Show-Help {
    @"
Usage: .\scripts\setup_dev.ps1 [-Help] [-Python VERSION] [-Pip] [-SkipPreCommit]

Set up a py-libp2p development environment on Windows.

Options:
  -Help / -h / -?     Show this help and exit
  -Python VERSION     Force Python version (e.g. 3.12); must be supported
  -Pip                Force pip even if uv is available
  -SkipPreCommit      Do not run pre-commit install

Python selection (default):
  Parse requires-python and Programming Language :: Python :: 3.X classifiers
  from pyproject.toml. Use the intersection (today 3.10-3.13). Pick the newest
  installed interpreter in that set.

Prerequisites:
  - CMake on PATH (winget install --id Kitware.CMake -e)
  - uv >= 0.13.4 on PATH unless -Pip (winget install --id=astral-sh.uv)
  - Git recommended (winget install --id Git.Git -e)
  - With -Pip: a supported system Python and pip >= 26.2.2
    (eMudhra/emSign CA incident; Discussion #1570)

If script execution is blocked:
  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
  or: pwsh -File scripts\setup_dev.ps1

Linux/macOS: use scripts/setup_dev.sh instead.
"@
}

function Get-VersionOrZero([string]$text) {
    if ([string]::IsNullOrWhiteSpace($text)) { return [version]"0.0.0" }
    $m = [regex]::Match($text, "(\d+\.\d+\.\d+|\d+\.\d+)")
    if (-not $m.Success) { return [version]"0.0.0" }
    $parts = $m.Groups[1].Value.Split(".")
    while ($parts.Count -lt 3) { $parts += "0" }
    return [version]::Parse(($parts[0..2] -join "."))
}

function Get-SupportedPythonMinors {
    $pyproject = Join-Path $PSScriptRoot "..\pyproject.toml" | Resolve-Path
    $text = Get-Content -Raw -Path $pyproject
    $minors = [System.Collections.Generic.List[string]]::new()

    foreach ($m in [regex]::Matches($text, 'Programming Language :: Python :: (3\.\d+)')) {
        $minors.Add($m.Groups[1].Value) | Out-Null
    }

    $req = [regex]::Match($text, 'requires-python\s*=\s*"([^"]+)"')
    $minMinor = 10
    $maxExclusiveMinor = 14
    if ($req.Success) {
        $spec = $req.Groups[1].Value.Replace(" ", "")
        foreach ($part in $spec.Split(",")) {
            if ($part.StartsWith(">=")) {
                $bits = $part.Substring(2).Split(".")
                if ($bits.Length -ge 2) { $minMinor = [int]$bits[1] }
            }
            elseif ($part.StartsWith("<") -and -not $part.StartsWith("<=")) {
                $bits = $part.Substring(1).Split(".")
                if ($bits.Length -ge 2) { $maxExclusiveMinor = [int]$bits[1] }
                elseif ($bits.Length -eq 1 -and $bits[0] -eq "4") { $maxExclusiveMinor = 14 }
            }
        }
    }

    if ($minors.Count -eq 0) {
        for ($i = $minMinor; $i -lt $maxExclusiveMinor; $i++) {
            $minors.Add("3.$i") | Out-Null
        }
    }

    $filtered = $minors | Sort-Object -Unique | Where-Object {
        $mm = [int]($_ -split "\.")[1]
        ($mm -ge $minMinor) -and ($mm -lt $maxExclusiveMinor)
    }
    return @($filtered)
}

function Find-PythonBin([string]$majorMinor) {
    $cmd = Get-Command "python$majorMinor" -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        try {
            $out = & py "-$majorMinor" -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $out) { return $out.Trim() }
        } catch { }
    }

    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        try {
            $found = & uv python find $majorMinor 2>$null
            if ($LASTEXITCODE -eq 0 -and $found) { return $found.Trim() }
        } catch { }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        try {
            $ver = & python -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>$null
            if ($ver -and $ver.Trim() -eq $majorMinor) { return $python.Source }
        } catch { }
    }
    return $null
}

function Resolve-Python([string[]]$supported, [string]$override) {
    if ($override) {
        $mm = ($override -split "\.")[0..1] -join "."
        if ($supported -notcontains $mm) {
            throw "Python $override is outside supported set: $($supported -join ', ')"
        }
        $bin = Find-PythonBin $mm
        if (-not $bin) { throw "Python $override not found on PATH / py / uv" }
        Write-Host "Selected Python $mm ($bin) via -Python" -ForegroundColor Green
        return @{ Version = $mm; Bin = $bin }
    }

    for ($i = $supported.Count - 1; $i -ge 0; $i--) {
        $s = $supported[$i]
        $bin = Find-PythonBin $s
        if ($bin) {
            Write-Host "Selected Python $s ($bin)" -ForegroundColor Green
            return @{ Version = $s; Bin = $bin }
        }
    }
    $newest = $supported[$supported.Count - 1]
    if (-not $Pip) {
        $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
        if ($uvCmd) {
            Write-Host "No supported Python on PATH; installing $newest via uv..." -ForegroundColor Yellow
            & uv python install $newest
            if ($LASTEXITCODE -ne 0) {
                throw "uv python install $newest failed"
            }
            $bin = Find-PythonBin $newest
            if ($bin) {
                Write-Host "Selected Python $newest ($bin) via uv python install" -ForegroundColor Green
                return @{ Version = $newest; Bin = $bin }
            }
            throw "Installed Python $newest with uv but could not locate it. Try: uv python find $newest"
        }
    }
    $hint = "No supported Python installed. Need one of: $($supported -join ', ')."
    if ($Pip) {
        $hint += " Install Python $newest from python.org or the Microsoft Store."
    }
    else {
        $hint += " Install uv (winget install --id=astral-sh.uv) then re-run."
    }
    throw $hint
}

function Test-SystemPrereqs {
    Write-Host "Checking system prerequisites..."
    $missing = $false
    $cmake = Get-Command cmake -ErrorAction SilentlyContinue
    if (-not $cmake) {
        Write-Host "  cmake: MISSING" -ForegroundColor Red
        $missing = $true
    }
    else {
        Write-Host "  cmake: OK ($($cmake.Source))" -ForegroundColor Green
    }

    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        $raw = (& uv --version) | Out-String
        $ver = Get-VersionOrZero $raw
        if ($ver -ge $MinUvVersion) {
            Write-Host "  uv: OK ($($uv.Source), $ver)" -ForegroundColor Green
        }
        else {
            Write-Host "  uv: TOO OLD ($ver < $MinUvVersion)" -ForegroundColor Red
            if (-not $Pip) { $missing = $true }
            else { Write-Host "       (-Pip: continuing without upgrading uv)" -ForegroundColor Yellow }
        }
    }
    else {
        Write-Host "  uv: MISSING" -ForegroundColor Red
        if (-not $Pip) { $missing = $true }
        else { Write-Host "       (-Pip: continuing without uv)" -ForegroundColor Yellow }
    }

    if ($missing) {
        if (-not $cmake) {
            Write-Host "Install cmake with: winget install --id Kitware.CMake -e"
        }
        if (-not $Pip -and -not (Get-Command uv -ErrorAction SilentlyContinue)) {
            Write-Host "Install uv with: winget install --id=astral-sh.uv"
            Write-Host "Or re-run with -Pip if you already have a supported system Python."
        }
        Write-Host "See docs/contributing.rst (Windows Development Setup)."
        exit 1
    }
}

function Ensure-Uv {
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uv) { return $false }
    $raw = (& uv --version) | Out-String
    $ver = Get-VersionOrZero $raw
    if ($ver -lt $MinUvVersion) {
        Write-Host "uv $ver is below $MinUvVersion; run: UV_SYSTEM_CERTS=true uv self update" -ForegroundColor Yellow
        Write-Host "Or reinstall: winget install --id=astral-sh.uv" -ForegroundColor Yellow
        exit 1
    }
    return $true
}

# --- main ---
if ($Help) {
    Show-Help
    exit 0
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

Write-Host "Setting up py-libp2p development environment (Windows)..." -ForegroundColor Green

$supported = Get-SupportedPythonMinors
if (-not $supported -or $supported.Count -eq 0) {
    throw "Could not parse supported Python versions from pyproject.toml"
}

Test-SystemPrereqs
$resolved = Resolve-Python -supported $supported -override $Python
$pyVer = $resolved.Version
$pyBin = $resolved.Bin

if (-not $Pip) {
    if (-not (Ensure-Uv)) {
        Write-Host "uv is required (or pass -Pip)." -ForegroundColor Red
        Write-Host "Install with: winget install --id=astral-sh.uv"
        exit 1
    }
    Write-Host "Using uv for installation (recommended)..." -ForegroundColor Green
    & uv sync --python $pyVer --group dev
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if (-not $SkipPreCommit) {
        Write-Host "Installing pre-commit hooks..." -ForegroundColor Green
        & uv run pre-commit install
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
}
else {
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        Write-Host "Creating virtual environment with $pyBin..." -ForegroundColor Yellow
        & $pyBin -m venv .venv
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    $pipVerRaw = & $venvPython -m pip --version | Out-String
    $pipVer = Get-VersionOrZero $pipVerRaw
    if ($pipVer -lt $MinPipVersion) {
        Write-Host "pip $pipVer is below $MinPipVersion; upgrading..." -ForegroundColor Yellow
        & $venvPython -m pip install --upgrade "pip>=$MinPipVersion"
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    Write-Host "Using pip for installation..." -ForegroundColor Green
    & $venvPython -m pip install --group dev -e .
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if (-not $SkipPreCommit) {
        Write-Host "Installing pre-commit hooks..." -ForegroundColor Green
        & $venvPython -m pre_commit install
        if ($LASTEXITCODE -ne 0) {
            & (Join-Path $repoRoot ".venv\Scripts\pre-commit.exe") install
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
    }
}

Write-Host "Setup complete! Run 'make pr' (Git Bash) or pytest via the venv." -ForegroundColor Green
Write-Host "Activate with: .\.venv\Scripts\Activate.ps1" -ForegroundColor Yellow
