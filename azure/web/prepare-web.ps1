param(
  [Parameter(Mandatory = $true)]
  [ValidatePattern('^https://[^/]+$')]
  [string]$ApiBaseUrl
)

$source = Split-Path -Parent $MyInvocation.MyCommand.Path
$destination = Join-Path $source 'dist'
New-Item -ItemType Directory -Path $destination -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $source 'index.html') -Destination $destination -Force
Copy-Item -LiteralPath (Join-Path $source 'styles.css') -Destination $destination -Force
Copy-Item -LiteralPath (Join-Path $source 'app.js') -Destination $destination -Force
Copy-Item -LiteralPath (Join-Path $source 'favicon.svg') -Destination $destination -Force
Copy-Item -LiteralPath (Join-Path $source 'staticwebapp.config.json') -Destination $destination -Force
$encodedUrl = ConvertTo-Json -InputObject $ApiBaseUrl -Compress
Set-Content -LiteralPath (Join-Path $destination 'config.js') -Value "window.RED_TELECORP_API_BASE_URL = $encodedUrl;" -Encoding utf8
Write-Output "Portal preparado en $destination"
