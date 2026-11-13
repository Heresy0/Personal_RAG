import {DatabaseSync} from 'node:sqlite';
import {createHash,randomUUID} from 'node:crypto';
import {mkdirSync} from 'node:fs';
import {dirname} from 'node:path';

export class Queue {
  constructor(filename) {
    mkdirSync(dirname(filename),{recursive:true});
    this.db=new DatabaseSync(filename);
    this.db.exec(`PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA busy_timeout=5000;
      CREATE TABLE IF NOT EXISTS jobs(
        id TEXT PRIMARY KEY, message_key TEXT NOT NULL UNIQUE, account TEXT NOT NULL, peer TEXT NOT NULL,
        body TEXT NOT NULL, received_at INTEGER NOT NULL, thread_id TEXT NOT NULL, workspace TEXT NOT NULL,
        state TEXT NOT NULL, rollout TEXT, offset INTEGER NOT NULL DEFAULT 0, carry TEXT NOT NULL DEFAULT '',
        turn_id TEXT, observed_turn TEXT, found INTEGER NOT NULL DEFAULT 0, final_text TEXT NOT NULL DEFAULT '',
        error TEXT, reply_offset INTEGER NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL,
        next_delivery INTEGER NOT NULL DEFAULT 0);
      CREATE INDEX IF NOT EXISTS job_order ON jobs(received_at,id);`);
  }
  close(){this.db.close();}
  recover(){
    // The command may already have queued input. Never automatically repeat it.
    this.db.prepare("UPDATE jobs SET state='uncertain',error='dispatch_interrupted' WHERE state='dispatching'").run();
  }
  enqueue({account,peer,messageId,body,threadId,workspace,receivedAt=Date.now()}) {
    const key=createHash('sha256').update(JSON.stringify([account,peer,messageId])).digest('hex');
    const existing=this.db.prepare('SELECT * FROM jobs WHERE message_key=?').get(key);
    if(existing){if(existing.body!==body)throw new Error('message_id_conflict');return {job:existing,duplicate:true};}
    const id=randomUUID(),now=Date.now();
    this.db.prepare(`INSERT INTO jobs(id,message_key,account,peer,body,received_at,thread_id,workspace,state,updated_at)
      VALUES(?,?,?,?,?,?,?,?,'pending',?)`).run(id,key,account,peer,body,receivedAt,threadId,workspace,now);
    return {job:this.get(id),duplicate:false};
  }
  get(id){return this.db.prepare('SELECT * FROM jobs WHERE id=?').get(id);}
  list(account,peer){return this.db.prepare('SELECT id,state,received_at,error FROM jobs WHERE account=? AND peer=? ORDER BY received_at DESC,id DESC LIMIT 20').all(account,peer);}
  active(){return this.db.prepare("SELECT * FROM jobs WHERE state IN ('pending','dispatching','queued','running','uncertain') ORDER BY received_at,id LIMIT 1").get();}
  replies(now=Date.now()){return this.db.prepare("SELECT * FROM jobs WHERE state='completed' AND next_delivery<=? ORDER BY received_at,id LIMIT 1").get(now);}
  update(id,values){
    const permitted=new Set(['state','rollout','offset','carry','turn_id','observed_turn','found','final_text','error','reply_offset','next_delivery']);
    if(Object.keys(values).some(k=>!permitted.has(k)))throw new Error('invalid_update');
    const entries=Object.entries({...values,updated_at:Date.now()});
    this.db.prepare(`UPDATE jobs SET ${entries.map(([k])=>k+'=?').join(',')} WHERE id=?`).run(...entries.map(([,v])=>v),id);
  }
  claim(id,rollout,offset){
    return this.db.prepare("UPDATE jobs SET state='dispatching',rollout=?,offset=?,error=NULL,updated_at=? WHERE id=? AND state='pending'").run(rollout,offset,Date.now(),id).changes===1;
  }
  cancel(id,account,peer){
    return this.db.prepare("UPDATE jobs SET state='cancelled',updated_at=? WHERE id=? AND account=? AND peer=? AND state='pending'").run(Date.now(),id,account,peer).changes===1;
  }
  acknowledge(id,account,peer){
    return this.db.prepare("UPDATE jobs SET state='reviewed',updated_at=? WHERE id=? AND account=? AND peer=? AND state IN ('uncertain','failed')").run(Date.now(),id,account,peer).changes===1;
  }
}
