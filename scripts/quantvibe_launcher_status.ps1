param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Backend', 'CountBridges', 'BridgeConnected', 'Diagnostic')]
    [string]$Mode,
    [string]$Server = 'http://127.0.0.1:8000',
    [string]$Account
)

$ErrorActionPreference = 'Stop'

function Get-Mt5Status {
    if ([string]::IsNullOrWhiteSpace($Account)) {
        throw 'A conta MT5 e obrigatoria para consultar o status da bridge.'
    }

    $uri = "$Server/api/mt5/status?account=$([uri]::EscapeDataString($Account))"
    return Invoke-RestMethod -Uri $uri -TimeoutSec 3
}

try {
    switch ($Mode) {
        'Backend' {
            $status = Invoke-RestMethod -Uri "$Server/api/status" -TimeoutSec 3
            if ($null -eq $status.version) { exit 1 }
            exit 0
        }
        'CountBridges' {
            $bridges = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
                Where-Object { $_.CommandLine -match 'quantvibe_mt5_bridge\.py' })
            $ids = @($bridges.ProcessId)
            $roots = @($bridges | Where-Object { $_.ParentProcessId -notin $ids })
            Write-Output $roots.Count
            exit 0
        }
        'BridgeConnected' {
            $status = Get-Mt5Status
            $accountMatches = $null -ne $status.session -and [string]$status.session.account -eq $Account
            if ($status.status -eq 'CONNECTED' -and $status.isLive -eq $true -and
                $status.dataSource -eq 'live' -and $accountMatches) {
                exit 0
            }
            exit 1
        }
        'Diagnostic' {
            $status = Get-Mt5Status
            Write-Host ("Estado={0} isLive={1} origem={2}" -f $status.status, $status.isLive, $status.dataSource)
            if ($status.lastError) { Write-Host ("Motivo={0}" -f $status.lastError) }
            if ($status.lastSuccessfulDataReadAt) {
                Write-Host ("Ultima leitura valida={0}" -f $status.lastSuccessfulDataReadAt)
            }
            exit 0
        }
    }
} catch {
    if ($Mode -eq 'Diagnostic') {
        Write-Host 'Nao foi possivel consultar o estado do backend.'
    }
    exit 1
}
