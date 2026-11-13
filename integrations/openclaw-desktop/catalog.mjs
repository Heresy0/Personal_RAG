import {DatabaseSync} from 'node:sqlite';
import {existsSync,readdirSync,realpathSync,statSync,readFileSync} from 'node:fs';
import {resolve,relative,isAbsolute,join} from 'node:path';
import {fileURLToPath} from 'node:url';

export const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export function plain(value){return value.replace(/^\\\\\?\\/,'');}
export function samePath(a,b){
  const normalize=x=>resolve(plain(x)).replace(/[\\/]+$/,'');
  return process.platform==='win32'?normalize(a).toLowerCase()===normalize(b).toLowerCase():normalize(a)===normalize(b);
}
function within(child,parent){const r=relative(realpathSync(parent),realpathSync(child));return r!==''&&!r.startsWith('..')&&!isAbsolute(r);}

/** Only reads the desktop's catalog. No thread/resume and no database writes. */
export function lookupThread(home,id,workspace) {
  if(!UUID.test(id)||!isAbsolute(workspace))throw new Error('invalid_desktop_binding');
  const candidates=readdirSync(home).filter(n=>/^state_\d+\.sqlite$/.test(n))
    .sort((a,b)=>Number(b.match(/\d+/)[0])-Number(a.match(/\d+/)[0]));
  if(!candidates.length)throw new Error('desktop_catalog_missing');
  const db=new DatabaseSync(join(home,candidates[0]),{readOnly:true});
  let row;
  try{db.exec('PRAGMA busy_timeout=2000');row=db.prepare('SELECT id,cwd,rollout_path,archived FROM threads WHERE id=?').get(id);}
  finally{db.close();}
  if(!row||row.archived||!samePath(row.cwd,workspace))throw new Error('desktop_thread_or_workspace_mismatch');
  const rollout=plain(row.rollout_path);
  if(!existsSync(rollout)||!within(rollout,join(home,'sessions'))||!statSync(rollout).isFile())throw new Error('invalid_rollout_path');
  return {id:row.id,workspace:plain(row.cwd),rollout};
}

if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  const config=JSON.parse(readFileSync(process.argv[2],'utf8'));
  const options=config.plugins.entries['personal-rag-desktop'].config;
  const thread=lookupThread(options.codexHome,options.threadId,options.workspace);
  console.log(JSON.stringify({desktopThreadVerified:true,threadId:thread.id,permissionsInherited:true}));
}
