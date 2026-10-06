// Encontra o playwright-core e o Chromium sem caminhos fixos de uma instalação temporária.
// Ordem: PLAYWRIGHT_CORE; node_modules normal; ~/.cache/planeamento-playwright (instalação local estável).
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const candidates=[process.env.PLAYWRIGHT_CORE,'playwright-core',
  path.join(os.homedir(),'.cache/planeamento-playwright/node_modules/playwright-core')].filter(Boolean);
let core;
for(const c of candidates){try{core=require(c);break}catch(e){if(e.code!=='MODULE_NOT_FOUND')throw e}}
if(!core)throw new Error('playwright-core não encontrado. Define PLAYWRIGHT_CORE ou instala em ~/.cache/planeamento-playwright.');
if(!process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE){
  const cache=path.join(os.homedir(),'.cache/ms-playwright');
  const found=(fs.existsSync(cache)?fs.readdirSync(cache):[]).filter(d=>/^chromium-\d+$/.test(d)).sort().reverse()
    .map(d=>path.join(cache,d,'chrome-linux64/chrome')).find(f=>fs.existsSync(f));
  if(found)process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE=found;
}
module.exports=core;
