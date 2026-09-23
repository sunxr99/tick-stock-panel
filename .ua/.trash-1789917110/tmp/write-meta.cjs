const fs = require('fs');
const path = require('path');
const child = require('child_process');
const root = process.argv[2];
const ua = path.join(root, '.ua');
const scan = JSON.parse(fs.readFileSync(path.join(ua, 'intermediate', 'scan-result.json'), 'utf8'));
const commit = child.execFileSync('git', ['-C', root, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
fs.writeFileSync(path.join(ua, 'meta.json'), JSON.stringify({ lastAnalyzedAt: new Date().toISOString(), gitCommitHash: commit, version: '1.0.0', analyzedFiles: scan.files.length }, null, 2));
