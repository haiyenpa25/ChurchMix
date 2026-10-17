import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn, spawnSync } from 'node:child_process';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
const port = Number(args[0] === '--port' ? args[1] : args[0]?.startsWith('--port=') ? args[0].slice(7) : process.env.PORT || 8080);
const validArgs = args.length === 0 || (args.length === 2 && args[0] === '--port') || (args.length === 1 && args[0].startsWith('--port='));
if (!validArgs || !Number.isInteger(port) || port < 1 || port > 65535) {
  console.error('Dùng npm start -- --port 8090 (cổng từ 1 đến 65535).');
  process.exit(1);
}
const candidates = [process.env.PYTHON];
if (process.platform === 'win32') {
  for (const version of ['314', '313', '312', '311']) {
    if (process.env.LOCALAPPDATA) candidates.push(path.join(process.env.LOCALAPPDATA, 'Programs', 'Python', `Python${version}`, 'python.exe'));
    candidates.push(path.join('C:\\', `Python${version}`, 'python.exe'));
  }
}
candidates.push('python3', 'python');
const python = candidates.filter(Boolean).find(executable => {
  if (path.isAbsolute(executable) && !fs.existsSync(executable)) return false;
  return spawnSync(executable, ['-c', 'import sys; assert sys.version_info >= (3,11)'], {timeout:5000, windowsHide:true, stdio:'ignore'}).status === 0;
});
if (!python) {
  console.error('Cần Python 3.11+ và thư viện trong requirements.txt. Có thể đặt biến PYTHON tới python.exe.');
  process.exit(1);
}
const server = spawn(python, ['-m','uvicorn','apps.api.main:app','--host','127.0.0.1','--port',String(port)], {cwd:root, stdio:'inherit', windowsHide:true});
server.on('error', error => { console.error(error.message); process.exitCode=1; });
server.on('exit', code => { process.exitCode=code ?? 1; });
for (const signal of ['SIGINT','SIGTERM']) process.on(signal, () => server.kill(signal));
