# ==========================
# MVZTEST - test zapret.ps1
# - Hidden cmd window (no flashing)
# - Waits for winws.exe to appear (real start), then tests
# - Clean output (no MVZ_BEST_BAT, no Results saved, no Restoring...)
# - Header: CONFIG TESTS
# - Optional ANSI per-word colors (OK/ERROR/UNSUP + Best config)
# ==========================

$hasErrors = $false

$rootDir = Split-Path $PSScriptRoot
$listsDir = Join-Path $rootDir "lists"
$utilsDir = Join-Path $rootDir "utils"
$resultsDir = Join-Path $utilsDir "test results"
if (-not (Test-Path $resultsDir)) { New-Item -ItemType Directory -Path $resultsDir | Out-Null }

$ipsetFlagFile = Join-Path $rootDir "ipset_switched.flag"

# -------- MVZ env (safe for $null) --------
$testTypeEnv = ("{0}" -f $env:MVZ_TESTTYPE).Trim().ToLower()
$modeEnv     = ("{0}" -f $env:MVZ_TESTMODE).Trim().ToLower()
$selectEnv   = ("{0}" -f $env:MVZ_TESTSELECT).Trim()
$pauseOnExit = (("{0}" -f $env:MVZ_PAUSE).Trim() -eq '1')

# Wait for winws to appear (sec), default 20
$winwsWaitSec = 20
$tmp = ("{0}" -f $env:MVZ_WINWS_WAIT).Trim()
if ($tmp -match '^\d+$') { $winwsWaitSec = [int]$tmp }

# Colors:
# - default: only when output is NOT redirected
# - MVZ_FORCE_COLOR=1 forces ANSI even if redirected
# - MVZ_NO_COLOR=1 disables ANSI always
$forceColor = (("{0}" -f $env:MVZ_FORCE_COLOR).Trim() -eq '1')
$noColor    = (("{0}" -f $env:MVZ_NO_COLOR).Trim() -eq '1')
$script:EnableAnsi = $false
try {
    $script:EnableAnsi = (-not $noColor) -and ($forceColor -or (-not [Console]::IsOutputRedirected))
} catch {
    $script:EnableAnsi = $false
}

# ---------------- ANSI helpers ----------------
function Get-AnsiCode {
    param([string]$ColorName)
    switch ($ColorName) {
        'Red'    { '31' }
        'Green'  { '32' }
        'Yellow' { '33' }
        'Cyan'   { '36' }
        'Gray'   { '90' }
        default  { '0' }
    }
}
function Ansi {
    param([string]$Text, [string]$ColorName)
    if (-not $script:EnableAnsi) { return $Text }
    $esc = [char]27
    $code = Get-AnsiCode $ColorName
    return "$esc[$code" + "m$Text$esc[0m"
}
function Status-Color {
    param([string]$Status)
    switch ($Status) {
        'OK'    { 'Green' }
        'ERROR' { 'Red' }
        'UNSUP' { 'Yellow' }
        default { 'Gray' }
    }
}
function Ping-Color {
    param([string]$Ping)
    if (-not $Ping) { return 'Gray' }
    if ($Ping -eq 'Timeout') { return 'Yellow' }
    return 'Cyan'
}

# ---------------- Core helpers ----------------
function Get-IpsetStatus {
    $listFile = Join-Path $listsDir "ipset-all.txt"
    if (-not (Test-Path $listFile)) { return "none" }
    $lineCount = (Get-Content $listFile | Measure-Object -Line).Lines
    if ($lineCount -eq 0) { return "any" }
    $hasDummy = Get-Content $listFile | Select-String -Pattern "203\.0\.113\.113/32" -Quiet
    if ($hasDummy) { return "none" } else { return "loaded" }
}

function Set-IpsetMode {
    param([string]$mode)
    $listFile = Join-Path $listsDir "ipset-all.txt"
    $backupFile = Join-Path $listsDir "ipset-all.test-backup.txt"
    if ($mode -eq "any") {
        if (Test-Path $listFile) { Copy-Item $listFile $backupFile -Force }
        else { "" | Out-File $backupFile -Encoding UTF8 }
        "" | Out-File $listFile -Encoding UTF8
    } elseif ($mode -eq "restore") {
        if (Test-Path $backupFile) { Move-Item $backupFile $listFile -Force }
    }
}

trap {
    Write-Output "[ERROR] Interrupted. Restoring ipset..."
    try {
        if ($script:originalIpsetStatus -and $script:originalIpsetStatus -ne "any") {
            Set-IpsetMode -mode "restore"
        }
    } catch {}
    try { Remove-Item -Path $ipsetFlagFile -ErrorAction SilentlyContinue } catch {}
    break
}

function New-OrderedDict { New-Object System.Collections.Specialized.OrderedDictionary }
function Add-OrSet {
    param($dict, $key, $val)
    if ($dict.Contains($key)) { $dict[$key] = $val } else { $dict.Add($key, $val) }
}

function Convert-Target {
    param([string]$Name, [string]$Value)

    if ($Value -like "PING:*") {
        $ping = $Value -replace '^PING:\s*', ''
        $url = $null
        $pingTarget = $ping
    } else {
        $url = $Value
        $pingTarget = $url -replace "^https?://", "" -replace "/.*$", ""
    }

    [PSCustomObject]@{
        Name       = $Name
        Url        = $url
        PingTarget = $pingTarget
    }
}

function Normalize-TargetName {
    param([string]$Name)
    if (-not $Name) { return $Name }
    ($Name -replace '\s+', '' -replace '\.', '')
}

function Test-ZapretServiceConflict {
    [bool](Get-Service -Name "zapret" -ErrorAction SilentlyContinue)
}

function Stop-Zapret {
    Get-Process -Name "winws" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}

function Get-WinwsSnapshot {
    try {
        Get-CimInstance Win32_Process -Filter "Name='winws.exe'" |
            Select-Object ProcessId, CommandLine, ExecutablePath
    } catch { @() }
}

function Start-ExeHidden {
    param(
        [Parameter(Mandatory)][string]$ExePath,
        [Parameter()][string]$Arguments = "",
        [Parameter()][string]$WorkingDir = ""
    )

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $ExePath
    $psi.Arguments = $Arguments
    if ($WorkingDir) { $psi.WorkingDirectory = $WorkingDir }

    # Hide cmd window; requires UseShellExecute=false for console processes. [web:204]
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden

    $p = New-Object System.Diagnostics.Process
    $p.StartInfo = $psi
    [void]$p.Start()
    return $p
}

function Start-BatHidden {
    param([Parameter(Mandatory)][string]$BatPath)

    $batDir = Split-Path $BatPath -Parent

    # Robust cmd quoting for paths with spaces/parentheses:
    # cmd /c ""C:\path with spaces\file.bat""  [web:231]
    # We also set WorkingDirectory to bat folder so relative paths work.
    $cmd = ('""{0}""' -f $BatPath)
    $args = ('/d /s /c {0}' -f $cmd)

    return Start-ExeHidden -ExePath "cmd.exe" -Arguments $args -WorkingDir $batDir
}

function Wait-NewWinwsStart {
    param(
        [int[]]$BeforeIds,
        [int]$TimeoutSec = 20
    )

    $end = (Get-Date).AddSeconds($TimeoutSec)
    do {
        $ps = @(Get-Process -Name "winws" -ErrorAction SilentlyContinue)
        if ($ps.Count -gt 0) {
            $new = $ps | Where-Object { $BeforeIds -notcontains $_.Id }
            if ($new) { return $true }
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $end)

    return $false
}

function Restore-WinwsSnapshot {
    param($snapshot)
    if (-not $snapshot -or $snapshot.Count -eq 0) { return }

    $current = @()
    try { $current = (Get-WinwsSnapshot).CommandLine } catch { $current = @() }

    foreach ($p in $snapshot) {
        if (-not $p.ExecutablePath) { continue }
        if ($current -and $current -contains $p.CommandLine) { continue }

        $exe = $p.ExecutablePath
        $processArgs = ""
        if ($p.CommandLine) {
            $quotedExe = '"' + $exe + '"'
            if ($p.CommandLine.StartsWith($quotedExe)) {
                $processArgs = $p.CommandLine.Substring($quotedExe.Length).Trim()
            } elseif ($p.CommandLine.StartsWith($exe)) {
                $processArgs = $p.CommandLine.Substring($exe.Length).Trim()
            }
        }

        try {
            Start-ExeHidden -ExePath $exe -Arguments $processArgs -WorkingDir (Split-Path $exe -Parent) | Out-Null
        } catch {}
    }
}

# ---------------- Targets ----------------
function Load-Targets {
    $targetList = @()
    $targetsFile = Join-Path $utilsDir "targets.txt"
    $rawTargets = New-OrderedDict

    if (Test-Path $targetsFile) {
        Get-Content $targetsFile | ForEach-Object {
            if ($_ -match '^\s*(\w+)\s*=\s*"(.+)"\s*$') {
                Add-OrSet -dict $rawTargets -key $matches[1] -val $matches[2]
            }
        }
    }

    if ($rawTargets.Count -eq 0) {
        Add-OrSet $rawTargets "DiscordMain"           "https://discord.com"
        Add-OrSet $rawTargets "DiscordGateway"        "https://gateway.discord.gg"
        Add-OrSet $rawTargets "DiscordCDN"            "https://cdn.discordapp.com"
        Add-OrSet $rawTargets "DiscordUpdates"        "https://updates.discord.com"
        Add-OrSet $rawTargets "YouTubeWeb"            "https://www.youtube.com"
        Add-OrSet $rawTargets "YouTubeShort"          "https://youtu.be"
        Add-OrSet $rawTargets "YouTubeImage"          "https://i.ytimg.com"
        Add-OrSet $rawTargets "YouTubeVideoRedirect"  "https://redirector.googlevideo.com"
        Add-OrSet $rawTargets "GoogleMain"            "https://www.google.com"
        Add-OrSet $rawTargets "GoogleGstatic"         "https://www.gstatic.com"
        Add-OrSet $rawTargets "CloudflareWeb"         "https://www.cloudflare.com"
        Add-OrSet $rawTargets "CloudflareCDN"         "https://cdnjs.cloudflare.com"
        Add-OrSet $rawTargets "CloudflareDNS1111"     "PING:1.1.1.1"
        Add-OrSet $rawTargets "CloudflareDNS1001"     "PING:1.0.0.1"
        Add-OrSet $rawTargets "GoogleDNS8888"         "PING:8.8.8.8"
        Add-OrSet $rawTargets "GoogleDNS8844"         "PING:8.8.4.4"
        Add-OrSet $rawTargets "Quad9DNS9999"          "PING:9.9.9.9"
    }

    foreach ($key in $rawTargets.Keys) {
        $targetList += Convert-Target -Name $key -Value $rawTargets[$key]
    }

    $targetList
}

function Format-StandardLine {
    param(
        [string]$NameOut,
        [bool]$IsUrl,
        [string]$HTTP,
        [string]$TLS12,
        [string]$TLS13,
        [string]$PingResult
    )

    if ($IsUrl) {
        $h  = Ansi $HTTP  (Status-Color $HTTP)
        $t2 = Ansi $TLS12 (Status-Color $TLS12)
        $t3 = Ansi $TLS13 (Status-Color $TLS13)
        $p  = Ansi $PingResult (Ping-Color $PingResult)

        "{0} : HTTP:{1} TLS1.2:{2} TLS1.3:{3} | Ping: {4}" -f $NameOut, $h, $t2, $t3, $p
    } else {
        $p  = Ansi $PingResult (Ping-Color $PingResult)
        "{0} : | Ping: {1}" -f $NameOut, $p
    }
}

# ---------------- Pre-flight checks ----------------
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Output ("[ERROR] " + (Ansi "Administrator" "Red") + " rights required.")
    $hasErrors = $true
}

if (-not (Get-Command "curl.exe" -ErrorAction SilentlyContinue)) {
    Write-Output ("[ERROR] " + (Ansi "curl.exe" "Red") + " not found.")
    $hasErrors = $true
}

if (Test-Path $ipsetFlagFile) {
    try { Set-IpsetMode -mode "restore" } catch {}
    try { Remove-Item -Path $ipsetFlagFile -ErrorAction SilentlyContinue } catch {}
}

$script:originalIpsetStatus = Get-IpsetStatus

if (Test-ZapretServiceConflict) {
    Write-Output ("[ERROR] Windows service " + (Ansi "'zapret'" "Red") + " is installed.")
    $hasErrors = $true
}

if ($hasErrors) { exit 1 }

# ---------------- Config list ----------------
$targetDir = $rootDir
$batFiles = Get-ChildItem -Path $targetDir -Filter "*.bat" |
    Where-Object { $_.Name -notlike "service*" } |
    Sort-Object { [Regex]::Replace($_.Name, "\d+", { $args[0].Value.PadLeft(8, "0") }) }

if (-not $batFiles -or $batFiles.Count -eq 0) {
    Write-Output "[ERROR] No *.bat files found."
    exit 1
}

# Type/mode (non-interactive)
$testType = 'standard'
if ($testTypeEnv -in @('standard')) { $testType = $testTypeEnv }

$mode = 'all'
if ($modeEnv -in @('all','select')) { $mode = $modeEnv }

if ($mode -eq 'select' -and $selectEnv) {
    $idxs = $selectEnv -split '[,\s]+' | Where-Object { $_ -match '^\d+$' } | ForEach-Object { [int]$_ } | Select-Object -Unique
    $picked = @()
    foreach ($i in $idxs) {
        if ($i -ge 1 -and $i -le $batFiles.Count) { $picked += $batFiles[$i-1] }
    }
    if ($picked.Count -gt 0) { $batFiles = $picked }
}

$targetList = Load-Targets
$originalWinws = Get-WinwsSnapshot
$globalResults = @()
$script:bestConfig = $null

# Header
Write-Output ""
Write-Output "============================================================"
Write-Output "CONFIG TESTS"
Write-Output ("Mode: {0}" -f $testType.ToUpper())
Write-Output ("Total configs: {0}" -f $batFiles.Count)
Write-Output "============================================================"
Write-Output ""

try {
    $configNum = 0
    foreach ($file in $batFiles) {
        $configNum++

        Stop-Zapret

        Write-Output ""
        Write-Output ("Config: {0} ({1}/{2})" -f $file.Name, $configNum, $batFiles.Count)

        $beforeIds = @()
        try { $beforeIds = @(Get-Process -Name "winws" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id) } catch { $beforeIds = @() }

        $proc = $null
        try {
            $proc = Start-BatHidden -BatPath $file.FullName
        } catch {
            Write-Output "  [ERROR] Failed to start .bat (cmd.exe launch error)."
            $globalResults += @{ Config = $file.Name; Type = $testType; Results = @() }
            continue
        }

        $started = Wait-NewWinwsStart -BeforeIds $beforeIds -TimeoutSec $winwsWaitSec
        if (-not $started) {
            Write-Output ("[ERROR] winws.exe not detected after {0}s (bat may not have started it)." -f $winwsWaitSec)
            $globalResults += @{ Config = $file.Name; Type = $testType; Results = @() }
            try { if ($proc -and -not $proc.HasExited) { $proc.Kill() | Out-Null } } catch {}
            continue
        }

        Start-Sleep -Milliseconds 600

        # -------- Tests (parallel) --------
        $curlTimeoutSeconds = 5
        $maxParallel = 8

        $runspacePool = [runspacefactory]::CreateRunspacePool(1, $maxParallel)
        $runspacePool.Open()

        $scriptBlock = {
            param($t, $curlTimeoutSeconds)

            $http = $null
            $tls12 = $null
            $tls13 = $null

            if ($t.Url) {
                $tests = @(
                    @{ Label = "HTTP";   Args = @("--http1.1") },
                    @{ Label = "TLS1.2"; Args = @("--tlsv1.2", "--tls-max", "1.2") },
                    @{ Label = "TLS1.3"; Args = @("--tlsv1.3", "--tls-max", "1.3") }
                )

                foreach ($test in $tests) {
                    $val = "ERROR"
                    try {
                        $baseArgs = @("-I", "-s", "-m", $curlTimeoutSeconds, "-o", "NUL", "-w", "%{http_code}")
                        $curlArgs = $baseArgs + $test.Args
                        $out = & curl.exe @curlArgs $t.Url 2>&1
                        $text = ($out | Out-String).Trim()

                        $unsupported = (($LASTEXITCODE -eq 35) -or ($text -match "does not support|not supported|unsupported protocol|TLS.*not supported|Unrecognized option|Unknown option|unsupported option|unsupported feature"))
                        if ($unsupported) { $val = "UNSUP" }
                        elseif ($LASTEXITCODE -eq 0) { $val = "OK" }
                        else { $val = "ERROR" }
                    } catch {
                        $val = "ERROR"
                    }

                    switch ($test.Label) {
                        "HTTP"   { $http  = $val }
                        "TLS1.2" { $tls12 = $val }
                        "TLS1.3" { $tls13 = $val }
                    }
                }
            }

            $pingResult = "n/a"
            if ($t.PingTarget) {
                try {
                    $pings = Test-Connection -ComputerName $t.PingTarget -Count 3 -ErrorAction Stop
                    $avg = ($pings | Measure-Object -Property ResponseTime -Average).Average
                    $pingResult = "{0:N0} ms" -f $avg
                } catch {
                    $pingResult = "Timeout"
                }
            }

            [PSCustomObject]@{
                Name       = $t.Name
                IsUrl      = [bool]$t.Url
                HTTP       = $http
                TLS12      = $tls12
                TLS13      = $tls13
                PingResult = $pingResult
            }
        }

        $runspaces = @()
        foreach ($target in $targetList) {
            $ps = [powershell]::Create().AddScript($scriptBlock)
            [void]$ps.AddArgument($target)
            [void]$ps.AddArgument($curlTimeoutSeconds)
            $ps.RunspacePool = $runspacePool

            $runspaces += [PSCustomObject]@{
                Powershell = $ps
                Handle     = $ps.BeginInvoke()
            }
        }

        $targetResults = @()
        foreach ($rs in $runspaces) {
            try {
                $waitMs = ([int]$curlTimeoutSeconds + 6) * 1000
                if ($rs.Handle -and $rs.Handle.AsyncWaitHandle) {
                    $null = $rs.Handle.AsyncWaitHandle.WaitOne($waitMs)
                }
            } catch {}

            try {
                $targetResults += $rs.Powershell.EndInvoke($rs.Handle)
            } catch {
                $targetResults += [PSCustomObject]@{ Name = 'UNKNOWN'; IsUrl = $true; HTTP='ERROR'; TLS12='ERROR'; TLS13='ERROR'; PingResult='Timeout' }
            }

            $rs.Powershell.Dispose()
        }

        $runspacePool.Close()
        $runspacePool.Dispose()

        $lookup = @{}
        foreach ($r in $targetResults) { $lookup[$r.Name] = $r }

        foreach ($t in $targetList) {
            $r = $lookup[$t.Name]
            if (-not $r) { continue }

            $nameOut = Normalize-TargetName $t.Name
            $line = Format-StandardLine -NameOut $nameOut -IsUrl $r.IsUrl -HTTP $r.HTTP -TLS12 $r.TLS12 -TLS13 $r.TLS13 -PingResult $r.PingResult
            Write-Output $line
        }

        $globalResults += @{ Config = $file.Name; Type = $testType; Results = $targetResults }

        Stop-Zapret
        try { if ($proc -and -not $proc.HasExited) { $proc.Kill() | Out-Null } } catch {}
    }

    # -------- Best config --------
    $analytics = @{}
    foreach ($res in $globalResults) {
        $cfg = $res.Config
        if (-not $analytics.ContainsKey($cfg)) {
            $analytics[$cfg] = @{ OK = 0; ERROR = 0; UNSUP = 0; PingOK = 0; PingFail = 0 }
        }

        foreach ($r in ($res.Results | Where-Object { $_ -ne $null })) {
            if ($r.PingResult -and $r.PingResult -ne "n/a" -and $r.PingResult -ne "Timeout") { $analytics[$cfg].PingOK++ } else { $analytics[$cfg].PingFail++ }

            if ($r.IsUrl) {
                foreach ($v in @($r.HTTP, $r.TLS12, $r.TLS13)) {
                    if ($v -eq "OK") { $analytics[$cfg].OK++ }
                    elseif ($v -eq "UNSUP") { $analytics[$cfg].UNSUP++ }
                    else { $analytics[$cfg].ERROR++ }
                }
            }
        }
    }

    $rows = foreach ($kv in $analytics.GetEnumerator()) {
        [PSCustomObject]@{
            Config = $kv.Key
            OK     = [int]$kv.Value.OK
            PingOK = [int]$kv.Value.PingOK
            ERROR  = [int]$kv.Value.ERROR
        }
    }

    $sortKeys = @(
        @{ Expression = 'OK';     Descending = $true  },
        @{ Expression = 'PingOK'; Descending = $true  },
        @{ Expression = 'ERROR';  Descending = $false }
    )

    $bestRow = $rows | Sort-Object -Property $sortKeys | Select-Object -First 1
    Write-Output ""
    if ($bestRow -and $bestRow.OK -gt 0) {
        $script:bestConfig = $bestRow.Config
        Write-Output ("Best config: {0}" -f (Ansi $script:bestConfig 'Green'))
    } else {
        $script:bestConfig = $null
        Write-Output "Best config: N/A"
    }

    # -------- Save results (silent) --------
    $dateStr = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
    $resultFile = Join-Path $resultsDir ("test_results_{0}.txt" -f $dateStr)
    "" | Out-File $resultFile -Encoding UTF8

    foreach ($res in $globalResults) {
        Add-Content $resultFile ("Config: {0} (Type: {1})" -f $res.Config, $res.Type)

        $byName = @{}
        foreach ($r in $res.Results) { $byName[$r.Name] = $r }

        foreach ($t in $targetList) {
            $r = $byName[$t.Name]
            if (-not $r) { continue }
            $nameOut = Normalize-TargetName $t.Name

            if ($r.IsUrl) {
                Add-Content $resultFile ("  {0} : HTTP:{1} TLS1.2:{2} TLS1.3:{3} | Ping: {4}" -f $nameOut, $r.HTTP, $r.TLS12, $r.TLS13, $r.PingResult)
            } else {
                Add-Content $resultFile ("  {0} : | Ping: {1}" -f $nameOut, $r.PingResult)
            }
        }

        Add-Content $resultFile ""
    }
    if ($script:bestConfig) { Add-Content $resultFile ("Best config: {0}" -f $script:bestConfig) }

    if ($pauseOnExit) { [void][System.Console]::ReadKey($true) }
    exit 0

} catch {
    Write-Output ("[ERROR] Fatal: {0}" -f $_.Exception.Message)
    if ($pauseOnExit) { [void][System.Console]::ReadKey($true) }
    exit 1

} finally {
    try { Stop-Zapret } catch {}
    try { Restore-WinwsSnapshot -snapshot $originalWinws } catch {}
    try {
        if ($script:originalIpsetStatus -and $script:originalIpsetStatus -ne "any") {
            Set-IpsetMode -mode "restore"
        }
    } catch {}
    try { Remove-Item -Path $ipsetFlagFile -ErrorAction SilentlyContinue } catch {}
}
