const fs = require('fs');
const path = require('path');
const root = process.argv[2];
const ua = path.join(root, '.ua');
const scan = JSON.parse(fs.readFileSync(path.join(ua, 'tmp', 'ua-clean-scan.json'), 'utf8'));
fs.writeFileSync(path.join(ua, 'tmp', 'ua-clean-import-input.json'), JSON.stringify({ projectRoot: root, files: scan.files }, null, 2));
