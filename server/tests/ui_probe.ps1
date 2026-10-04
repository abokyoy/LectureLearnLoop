# 1) 本地后端 6021 探活  2) Stitch MCP (HTTP JSON-RPC) initialize 探活
$ErrorActionPreference = 'Continue'
$out = @()

# --- local server ---
try {
  $r = Invoke-WebRequest -Uri 'http://127.0.0.1:6021/' -UseBasicParsing -MaximumRedirection 5 -TimeoutSec 8
  $out += "server6021=HTTP $($r.StatusCode), len=$($r.Content.Length)"
} catch {
  $out += "server6021=ERR $($_.Exception.Message)"
}

# --- Stitch MCP via streamable HTTP ---
$env:HTTP_PROXY = 'http://127.0.0.1:10808'
$env:HTTPS_PROXY = 'http://127.0.0.1:10808'
$env:NO_PROXY = 'localhost,127.0.0.1'
$key = '*REMOVED-BY-FILTER-REPO*'
$body = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"qoder-probe","version":"1.0"}}}'
try {
  $headers = @{ 'X-Goog-Api-Key' = $key; 'Content-Type' = 'application/json'; 'Accept' = 'application/json, text/event-stream' }
  $r2 = Invoke-WebRequest -Uri 'https://stitch.googleapis.com/mcp' -Method Post -Headers $headers -Body $body -UseBasicParsing -TimeoutSec 30 -Proxy 'http://127.0.0.1:10808'
  $snippet = $r2.Content
  if ($snippet.Length -gt 600) { $snippet = $snippet.Substring(0, 600) }
  $out += "stitch=HTTP $($r2.StatusCode) mcp-session=$($r2.Headers['mcp-session-id']) body=$snippet"
} catch {
  $resp = $_.Exception.Response
  if ($resp -ne $null) {
    try { $sr = New-Object System.IO.StreamReader($resp.GetResponseStream()); $errBody = $sr.ReadToEnd(); if ($errBody.Length -gt 400) { $errBody = $errBody.Substring(0,400) } } catch { $errBody = '' }
    $out += "stitch=HTTP $([int]$resp.StatusCode) body=$errBody"
  } else {
    $out += "stitch=ERR $($_.Exception.Message)"
  }
}

$out | Set-Content -Path 'e:\LLM\LectureLearnLoop\server\logs\ui_probe.txt' -Encoding UTF8
