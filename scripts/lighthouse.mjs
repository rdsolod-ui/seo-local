import fs from 'node:fs';
import lighthouse from 'lighthouse';
import * as chromeLauncher from 'chrome-launcher';
import desktop from 'lighthouse/core/config/desktop-config.js';

const [url, mode, proxy, output] = process.argv.slice(2);
let chrome;
async function cleanup() { if (chrome) { const c=chrome; chrome=null; await c.kill(); } }
const timer=setTimeout(async()=>{await cleanup();process.exit(2);},170000);
for(const signal of ['SIGTERM','SIGINT']) process.on(signal, async()=>{await cleanup();process.exit(2);});
try {
  chrome=await chromeLauncher.launch({chromePath:process.env.CHROME_PATH || undefined, chromeFlags:[
    '--headless=new','--disable-gpu','--disable-dev-shm-usage','--disable-quic',
    '--disable-background-networking','--disable-extensions',
    `--proxy-server=http://127.0.0.1:${proxy}`,'--proxy-bypass-list=<-loopback>',
    '--force-webrtc-ip-handling-policy=disable_non_proxied_udp'
  ]});
  const result=await lighthouse(url, {port:chrome.port, output:'json', logLevel:'error',
    onlyCategories:['performance','accessibility','best-practices','seo'], maxWaitForLoad:45000}, mode==='desktop'?desktop:undefined);
  fs.writeFileSync(output,JSON.stringify(result.lhr));
} catch(error) { console.error(error.message);process.exitCode=1; }
finally {clearTimeout(timer);await cleanup();}
