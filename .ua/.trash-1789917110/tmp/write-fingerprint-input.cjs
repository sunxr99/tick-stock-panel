const fs = require('fs');
const path = require('path');
const child = require('child_process');
const root = process.argv[2];
const ua = path.join(root, '.ua');
const scan = JSON.parse(fs.readFileSync(path.join(ua, 'intermediate', 'scan-result.json'), 'utf8'));
const commit = child.execFileSync('git', ['-C', root, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
fs.writeFileSync(path.join(ua, 'intermediate', 'fingerprint-input.json'), JSON.stringify({ projectRoot: root, filePaths: scan.files.map(file => file.path), gitCommitHash: commit }, null, 2));
console.log(JSON.stringify({ files: scan.files.length, commit }));
