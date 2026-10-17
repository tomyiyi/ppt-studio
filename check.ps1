<#
check.ps1 -- ppt-studio one-shot self check (Windows primary dev box)

Usage:
  .\check.ps1                    run every scripts/test_*.py gate + env probes
  .\check.ps1 -NoRender          skip gates that need chromium (slow)
  .\check.ps1 -Only "test_plan_contract,test_qa_scale"
                                 run only scripts whose name matches (comma separated, .py optional)

Exit code: 0 all green; 1 something failed; 2 no python found.
Encoding note: this file is deliberately PURE ASCII (see the host rule: PS 5.1
mis-decodes non-ASCII .ps1 without a BOM, and any later edit drops the BOM).
Chinese still shows up in the test output because PYTHONUTF8 + UTF-8 console.
#>
param(
    [switch]$NoRender,
    [string]$Only = ""
)

$ErrorActionPreference = 'Continue'
$Repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONUTF8 = '1'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$results = @()

# gates that need a browser (slow: seconds to tens of seconds each)
$SLOW = @('test_image_route.py', 'test_topic_to_deck.py', 'test_qa_layout_fixes.py')

function Step($name, $ok, $detail, $skipped = $false) {
    $tag = if ($skipped) { 'SKIP' } elseif ($ok) { 'PASS' } else { 'FAIL' }
    $color = if ($skipped) { 'DarkGray' } elseif ($ok) { 'Green' } else { 'Red' }
    Write-Host ("  [{0,-4}] {1,-34} {2}" -f $tag, $name, $detail) -ForegroundColor $color
    $script:results += [pscustomobject]@{ Name = $name; Tag = $tag }
}

Write-Host "`n=== ppt-studio self check ($Repo) ===" -ForegroundColor Cyan

# ---------- 1. interpreter ----------
$Py = $null
foreach ($c in @((Join-Path $Repo '.venv\Scripts\python.exe'),
                 (Join-Path $Repo '.venv\bin\python'),
                 'python')) {
    if ($c -eq 'python') { if (Get-Command python -ErrorAction SilentlyContinue) { $Py = 'python'; break } }
    elseif (Test-Path $c) { $Py = $c; break }
}
if (-not $Py) {
    Write-Host "  [FAIL] python            no venv or system python: python -m venv .venv; .venv\Scripts\pip install -r requirements.txt" -ForegroundColor Red
    exit 2
}
$ver = (& $Py --version) 2>&1
Step 'python' $true "$Py ($ver)"

# ---------- 2. deps ----------
foreach ($m in @('playwright', 'PIL')) {
    & $Py -c "import $m" 2>&1 | Out-Null
    $depOk = $LASTEXITCODE -eq 0
    $hint = if ($depOk) { 'ok' } else { 'FAILED: pip install -r requirements.txt' }
    Step "import $m" $depOk $hint
}

# ---------- 3. rasterize engines (on Windows only the chromium route can work) ----------
$probe = "import sys; sys.path.insert(0, r'$Repo\scripts'); import vector_illustration as VI; print(VI.cairo_available() or 'None')"
$cairoRaw = ((& $Py -c $probe 2>&1) | Select-Object -Last 1) -join ''
$pw = $env:PLAYWRIGHT_BROWSERS_PATH
if (-not $pw) { $pw = Join-Path $env:LOCALAPPDATA 'ms-playwright' }
$hasChromium = Test-Path (Join-Path $pw 'chromium-*')
$cHint = if ($hasChromium) { 'yes' } else { 'no' }
Step 'rasterize engines' ($cairoRaw -ne 'None' -or $hasChromium) "cairo=$cairoRaw / chromium=$cHint (either route is enough)"

# ---------- 4. gateway (report only, never fails the run) ----------
$keyFile = Join-Path $env:USERPROFILE '.new-api\local_key.json'
if (Test-Path $keyFile) {
    $cfg = Get-Content $keyFile -Raw -Encoding UTF8 | ConvertFrom-Json
    $u = ($cfg.base_url -replace '/v1/?$', '') + '/v1/models'
    try {
        Invoke-WebRequest $u -Headers @{ Authorization = "Bearer $($cfg.api_key)" } -TimeoutSec 3 -UseBasicParsing | Out-Null
        Step 'new-api gateway' $true "$u reachable"
    } catch {
        Step 'new-api gateway' $true "$u unreachable (image-gen chain down; asset/vector local routes unaffected)"
    }
} else {
    Step 'new-api gateway' $true "no $keyFile (agnes image route would be deferred)"
}

# ---------- 5. gates ----------
$tests = Get-ChildItem (Join-Path $Repo 'scripts') -Filter 'test_*.py' | Sort-Object Name
foreach ($t in $tests) {
    if ($Only) {
        $matched = $false
        foreach ($pat in ($Only -split '[,;]')) { if ($t.BaseName -match $pat.Trim()) { $matched = $true } }
        if (-not $matched) { continue }
    }
    if ($NoRender -and ($SLOW -contains $t.Name)) { Step $t.BaseName $true '-NoRender' $true; continue }
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $out = & $Py $t.FullName 2>&1
    $code = $LASTEXITCODE
    $sw.Stop()
    Step $t.BaseName ($code -eq 0) ("{0:N1}s  {1}" -f $sw.Elapsed.TotalSeconds, (($out | Select-Object -Last 1) -join ''))
}

# ---------- summary ----------
$fail = @($results | Where-Object { $_.Tag -eq 'FAIL' })
$sumColor = if ($fail.Count) { 'Red' } else { 'Green' }
Write-Host ("`n=== {0} checks, {1} failed ===" -f $results.Count, $fail.Count) -ForegroundColor $sumColor
if ($fail.Count) { $fail | ForEach-Object { Write-Host ("  X " + $_.Name) -ForegroundColor Red } }
exit $(if ($fail.Count) { 1 } else { 0 })
