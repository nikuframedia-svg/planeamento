param(
 [Parameter(Mandatory=$true)][ValidateSet('cpis','original')][string]$Source,
 [Parameter(Mandatory=$true)][string]$Python,
 [switch]$Check,
 [switch]$Watch
)
$ErrorActionPreference='Stop'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Indica o Python existente da aplicação MES.' }
$config=Join-Path $PSScriptRoot ($Source+'.env')
if (-not (Test-Path -LiteralPath $config)) { throw "Configura $Source.env a partir do exemplo. Não contém credenciais de origem pré-preenchidas." }
Get-Content -LiteralPath $config | ForEach-Object {
 $line=$_.Trim()
 if ($line -and -not $line.StartsWith('#') -and $line.Contains('=')) {
  $i=$line.IndexOf('=')
  $key=$line.Substring(0,$i).Trim()
  $value=$line.Substring($i+1).Trim().Trim('"').Trim("'")
  Set-Item -Path ('Env:'+$key) -Value $value
 }
}
if ($Check -and $Watch) { throw 'Escolhe verificação ou execução contínua.' }
Set-Location $PSScriptRoot
if ($Source -eq 'cpis') {
 if ($Check) { throw 'Para o diagnóstico CPIS usa diagnose_cpis_readonly.ps1 -Workbook caminho.xlsm.' }
 if (-not $env:CPIS_DSN -or -not $env:CPIS_PUBLISH_DSN) { throw 'Configura separadamente CPIS_DSN e CPIS_PUBLISH_DSN.' }
 # Explicit publication credentials for this isolated process only.
 $env:MES_PG_DSN=$env:CPIS_PUBLISH_DSN
 $module='raw_connectors.cpis_sync'
} else {
 if (-not $env:ORIGINAL_OCR_SQLITE_PATH -or -not $env:ORIGINAL_OCR_INSTANCE_ID) { throw 'Confirma a SQLite ativa e a identidade persistente da instância.' }
 $module='raw_connectors.original_ocr'
}
$argsList=@('-m',$module)
if ($Check) {$argsList+='--check'}
if ($Watch) {$argsList+='--watch'}
if ($Watch) {
 $logs=Join-Path $PSScriptRoot 'logs';New-Item -ItemType Directory -Force -Path $logs | Out-Null
 & $Python @argsList *>> (Join-Path $logs ($Source+'.log'))
} else { & $Python @argsList }
exit $LASTEXITCODE
