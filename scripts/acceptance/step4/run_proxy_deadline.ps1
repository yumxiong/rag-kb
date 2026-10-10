# Run only via an approved, elevated local Docker acceptance command.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RunDirectory,
    [Parameter(Mandatory = $true)][string]$EvidenceDirectory
)

$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..'))
$run = [IO.Path]::GetFullPath($RunDirectory)
$evidence = [IO.Path]::GetFullPath($EvidenceDirectory)
if (-not $run.StartsWith(($root + '\.step4-run\'), [StringComparison]::OrdinalIgnoreCase) -or
    -not $evidence.StartsWith(($root + '\.step4-evidence\'), [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Acceptance paths must stay in their workspace directories'
}
$suffix = [Guid]::NewGuid().ToString('N').Substring(0, 8)
$network = "rag-step4-proxy-$suffix"
$backend = "rag-step4-backend-$suffix"
$gateway = "rag-step4-gateway-$suffix"
$client = "rag-step4-client-$suffix"
$image = 'sha256:168bc2ec9e66a7f8f749996fcf882b1f7f4f1662c0dc27f1375948938b553387'
$createdNetwork = $false
$createdBackend = $false
$createdGateway = $false
$clientExit = 1

function Invoke-LocalDocker {
    $ErrorActionPreference = 'Continue'
    & docker @args
    $dockerExit = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($dockerExit -ne 0) { throw "Local Docker command failed: $($args[0])" }
}

try {
    Invoke-LocalDocker network create --internal --subnet 172.30.244.0/24 $network
    $createdNetwork = $true
    $backendArgs = @(
        'run','-d','--rm','--name',$backend,'--network',$network,'--ip','172.30.244.2',
        '--network-alias','backend','--read-only','--cap-drop','ALL',
        '--security-opt','no-new-privileges','--no-healthcheck','--workdir','/tmp',
        '--tmpfs','/tmp:rw,exec,nosuid,size=512m','--tmpfs','/app:rw,noexec,nosuid,size=1m',
        '--mount',"type=bind,source=$run\source,target=/workspace,readonly",
        '--mount',"type=bind,source=$run\proxy,target=/acceptance,readonly",
        '--mount',"type=bind,source=$evidence,target=/evidence",
        '--entrypoint','/usr/bin/env',$image,'-i',
        'PATH=/usr/local/bin:/usr/bin:/bin','HOME=/tmp','LANG=C.UTF-8',
        'PYTHONPATH=/workspace:/acceptance','PYTHONDONTWRITEBYTECODE=1',
        'PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring',
        'UPLOAD_DIR=/tmp/uploads','CHROMA_DB_PATH=/tmp/chroma',
        'JOB_STATUS_DIR=/tmp/jobs','TEMP_UPLOAD_DIR=/tmp/uploads-tmp',
        'QUOTA_STORAGE_PATH=/tmp/quota','ANONYMOUS_STORE_REFERENCE=/tmp/reference/store.json',
        'ANONYMOUS_STORAGE_DEVELOPMENT=true','ANONYMOUS_COOKIE_SECURE=false',
        'STEP4_EVIDENCE=/evidence','python','-m','uvicorn','proxy_deadline_fixture:app',
        '--host','0.0.0.0','--port','8000','--workers','1','--proxy-headers',
        '--forwarded-allow-ips','172.30.244.3','--no-access-log','--log-level','warning'
    )
    Invoke-LocalDocker @backendArgs
    $createdBackend = $true
    $nginxArgs = @(
        'run','--rm','--network',$network,'--read-only','--user','65534:65534',
        '--cap-drop','ALL','--security-opt','no-new-privileges',
        '--tmpfs','/tmp:rw,nosuid,size=64m',
        '--mount',"type=bind,source=$run\proxy\nginx.conf,target=/acceptance-nginx.conf,readonly",
        '--entrypoint','nginx','nginx:alpine','-e','/tmp/nginx-error.log',
        '-c','/acceptance-nginx.conf','-t'
    )
    Invoke-LocalDocker @nginxArgs
    $gatewayArgs = @(
        'run','-d','--rm','--name',$gateway,'--network',$network,'--ip','172.30.244.3',
        '--network-alias','gateway','--read-only','--user','65534:65534','--cap-drop','ALL',
        '--security-opt','no-new-privileges','--tmpfs','/tmp:rw,nosuid,size=64m',
        '--mount',"type=bind,source=$run\proxy\nginx.conf,target=/acceptance-nginx.conf,readonly",
        '--entrypoint','nginx','nginx:alpine','-e','/tmp/nginx-error.log',
        '-c','/acceptance-nginx.conf','-g','daemon off;'
    )
    Invoke-LocalDocker @gatewayArgs
    $createdGateway = $true
    $clientArgs = @(
        'run','--rm','--name',$client,'--network',$network,'--ip','172.30.244.4',
        '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
        '--no-healthcheck','--workdir','/tmp','--tmpfs','/tmp:rw,nosuid,size=128m',
        '--mount',"type=bind,source=$run\proxy,target=/acceptance,readonly",
        '--mount',"type=bind,source=$evidence,target=/evidence",
        '--entrypoint','/usr/bin/env',$image,'-i','PATH=/usr/local/bin:/usr/bin:/bin',
        'HOME=/tmp','LANG=C.UTF-8','PYTHONDONTWRITEBYTECODE=1','PYTHONUNBUFFERED=1',
        'STEP4_EVIDENCE=/evidence','STEP4_CLIENT_IP=172.30.244.4',
        'python','/acceptance/proxy_deadline_checks.py'
    )
    $ErrorActionPreference = 'Continue'
    & docker @clientArgs
    $clientExit = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    Write-Output "PROXY_CHECK_EXIT_CODE: $clientExit"
} finally {
    if ($createdGateway) { Invoke-LocalDocker stop --time 10 $gateway }
    if ($createdBackend) { Invoke-LocalDocker stop --time 90 $backend }
    if ($createdNetwork) { Invoke-LocalDocker network rm $network }
}
exit $clientExit
