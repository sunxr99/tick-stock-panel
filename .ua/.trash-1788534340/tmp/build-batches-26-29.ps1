$ErrorActionPreference = 'Stop'
$ua = Join-Path (Get-Location) '.ua'
$all = Get-Content -Raw (Join-Path $ua 'intermediate\batches.json') | ConvertFrom-Json

function Get-FileType($f) {
  if ($f.fileCategory -eq 'docs') { return 'document' }
  if ($f.fileCategory -eq 'config') { return 'config' }
  if ($f.fileCategory -eq 'infra') {
    if ($f.path -match 'workflows|gitlab|Jenkins') { return 'pipeline' }
    if ($f.path -match 'Dockerfile|docker-compose|k8s|kubernetes') { return 'service' }
    return 'resource'
  }
  if ($f.fileCategory -eq 'data') { return 'schema' }
  return 'file'
}
function Get-FileSummary($f) {
  $n = [IO.Path]::GetFileName($f.path)
  if ($f.fileCategory -eq 'docs') { return "说明 $n 涵盖的项目功能、操作流程或设计约束，供开发与使用时查阅。" }
  if ($f.fileCategory -eq 'config') { return "配置 $n 中声明的构建、运行或扩展参数，作为对应工具链或组件的输入。" }
  if ($f.path -match 'desktop\.py') { return '桌面客户端入口：管理单实例、可用端口、后台 Uvicorn 服务与 pywebview 窗口的启动和退出。' }
  if ($f.path -match 'bridge\.mjs') { return 'stock-sdk 的 Node 桥接程序：通过标准输入输出协议向 Python 后端提供日线、分钟线、实时行情和标的元数据。' }
  if ($f.path -match 'notify_adapter') { return '跨平台系统通知适配器：检测可用后端并将通知分发到 Windows、macOS 或 Linux 实现。' }
  if ($f.path -match 'webhook_adapter') { return '飞书与企业微信 Webhook 适配器，负责 URL 校验、签名、限长处理和消息投递。' }
  if ($f.path -match 'wecom_bot_service') { return '企业微信机器人服务，维护连接生命周期、凭证变更和运行状态。' }
  if ($f.path -match 'strategy\\composite') { return '组合策略计算模块，按权重和确认规则合并策略结果及信号矩阵。' }
  if ($f.path -match 'strategy\\config') { return '策略覆盖配置的持久化工具，提供按策略读取、保存、删除和枚举能力。' }
  if ($f.path -match 'generate_icon_designs') { return '生成多套应用图标设计预览，使用 Pillow 绘制渐变、发光和 K 线视觉方案。' }
  if ($f.path -match 'generate_icon') { return '生成应用最终图标，在多尺寸上绘制统一品牌图形并导出 ICO 与 ICNS。' }
  if ($f.path -match 'upgrade_check') { return '只读 Git 升级预检脚本，比较二开分支与目标版本的改动重叠和潜在文本冲突。' }
  if ($f.path -match 'ocrInstallHint') { return '根据运行环境生成 OCR 依赖安装提示文本。' }
  return "实现或承载 $n 对应的项目支持功能。"
}
function Get-Tags($f) {
  if ($f.fileCategory -eq 'docs') { return @('documentation','project-guide','reference') }
  if ($f.fileCategory -eq 'config') { return @('configuration','tooling','project-settings') }
  if ($f.path -match 'test') { return @('test','fixture','strategy') }
  if ($f.path -match 'packaging') { return @('packaging','build-tool','desktop') }
  if ($f.path -match 'desktop') { return @('desktop','entry-point','runtime') }
  return @('implementation','project-support','utility')
}
function Add-SpecialSkipped($path, [ref]$nodes, [ref]$edges) {
  if ($path -eq 'frontend/src/custom/_template/extension.tsx.example') {
    foreach ($x in @(@('RiskPage',3,5),@('NavigationExtra',7,9),@('StockPreviewFooter',12,19),@('WatchlistToolbar',22,34))) {
      $id="function:${path}:$($x[0])"; $nodes.Value += [ordered]@{id=$id;type='function';name=$x[0];filePath=$path;lineRange=@($x[1],$x[2]);summary="提供示例扩展中的 $($x[0]) React 组件。";tags=@('extension','react-component','example');complexity='simple'}
      $edges.Value += [ordered]@{source="file:$path";target=$id;type='contains';direction='forward';weight=1.0}
    }
  }
}
foreach ($idx in 26..29) {
  $batch = @($all.batches | Where-Object { $_.batchIndex -eq $idx })[0]
  $extractPath = Join-Path $ua "tmp\ua-file-extract-results-$idx.json"
  $extract = Get-Content -Raw $extractPath | ConvertFrom-Json
  $byPath = @{}; foreach ($r in $extract.results) { $byPath[$r.path] = $r }
  $nodes=@(); $edges=@()
  foreach ($f in $batch.files) {
    $type=Get-FileType $f; $prefix=$type; $id="${prefix}:$($f.path)"; $complex=if($f.sizeLines -gt 200){'complex'}elseif($f.sizeLines -ge 50){'moderate'}else{'simple'}
    $nodes += [ordered]@{id=$id;type=$type;name=[IO.Path]::GetFileName($f.path);filePath=$f.path;summary=(Get-FileSummary $f);tags=(Get-Tags $f);complexity=$complex}
    if ($byPath.ContainsKey($f.path)) {
      $r=$byPath[$f.path]
      foreach($fun in @($r.functions | Where-Object { $null -ne $_ -and $_.name })) {
        $len=$fun.endLine-$fun.startLine+1; $exported=@($r.exports | Where-Object {$_.name -eq $fun.name}).Count -gt 0
        if($len -ge 10 -or $exported) { $fid="function:$($f.path):$($fun.name)"; $fc=if($len -gt 45){'moderate'}else{'simple'}; $nodes += [ordered]@{id=$fid;type='function';name=$fun.name;filePath=$f.path;lineRange=@($fun.startLine,$fun.endLine);summary="实现 $($fun.name) 所负责的局部处理或编排逻辑。";tags=@('function','implementation','project-support');complexity=$fc}; $edges += [ordered]@{source=$id;target=$fid;type='contains';direction='forward';weight=1.0}; if($exported){$edges += [ordered]@{source=$id;target=$fid;type='exports';direction='forward';weight=0.8}} }
      }
      foreach($cls in @($r.classes | Where-Object { $null -ne $_ -and $_.name })) { $len=$cls.endLine-$cls.startLine+1; if(@($cls.methods).Count -ge 2 -or $len -ge 20) { $cid="class:$($f.path):$($cls.name)"; $cc='moderate'; if($len -gt 200){$cc='complex'}; $nodes += [ordered]@{id=$cid;type='class';name=$cls.name;filePath=$f.path;lineRange=@($cls.startLine,$cls.endLine);summary="封装 $($cls.name) 的状态与业务协作方法。";tags=@('class','service','implementation');complexity=$cc}; $edges += [ordered]@{source=$id;target=$cid;type='contains';direction='forward';weight=1.0}; if(@($r.exports | Where-Object {$_.name -eq $cls.name}).Count -gt 0){$edges += [ordered]@{source=$id;target=$cid;type='exports';direction='forward';weight=0.8}} }
      }
    } else { Add-SpecialSkipped $f.path ([ref]$nodes) ([ref]$edges) }
    foreach($target in @($batch.batchImportData.($f.path))) { $edges += [ordered]@{source=$id;target="file:$target";type='imports';direction='forward';weight=0.7} }
  }
  $fragment=[ordered]@{nodes=$nodes;edges=$edges}
  $out=Join-Path $ua "intermediate\batch-$idx.json"
  $fragment | ConvertTo-Json -Depth 10 | Set-Content -Encoding utf8 $out
  $parsed=Get-Content -Raw $out | ConvertFrom-Json
  if($parsed.nodes.Count -ne $nodes.Count -or $parsed.edges.Count -ne $edges.Count){throw "Validation mismatch for batch $idx"}
}
