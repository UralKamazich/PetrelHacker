const path = require('path');
const { spawn } = require('child_process');
const electronPath = require('electron');

const env = Object.assign({}, process.env);
delete env.ELECTRON_RUN_AS_NODE;

const child = spawn(electronPath, [path.resolve(__dirname, '..')], {
  stdio: 'inherit',
  env
});

child.on('close', code => {
  process.exit(code || 0);
});
