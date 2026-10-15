"""Typed SQLite repositories.  All group operations carry an explicit group ID."""
from __future__ import annotations
import base64, hashlib, json, sqlite3
from datetime import datetime, timezone
from typing import Any
from .models import AuditEvent, Cursor, PoolOption

def _now() -> datetime: return datetime.now(timezone.utc)
def _dt(value: str | datetime) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)
def _s(value: datetime) -> str: return value.isoformat()

class SQLiteAbuseControl:
    def __init__(self, db: sqlite3.Connection) -> None: self.db = db
    def _id(self, bucket: str, key: str) -> str: return hashlib.sha256((bucket+"\0"+key).encode()).hexdigest()
    def check(self, bucket: str, key: str, limit: int, window_seconds: int) -> bool:
        row = self.db.execute("SELECT count,expires_at FROM abuse_control WHERE id=?", (self._id(bucket,key),)).fetchone()
        return row is None or _dt(row[1]) <= _now() or row[0] < limit
    def record(self, bucket: str, key: str, limit: int, window_seconds: int) -> bool:
        now = _now(); ident = self._id(bucket,key); expiry = now.timestamp()+window_seconds
        with self.db:
            row = self.db.execute("SELECT count,expires_at FROM abuse_control WHERE id=?", (ident,)).fetchone()
            if row and _dt(row[1]) > now and row[0] >= limit: return False
            if row and _dt(row[1]) > now: self.db.execute("UPDATE abuse_control SET count=count+1 WHERE id=?", (ident,))
            else: self.db.execute("INSERT OR REPLACE INTO abuse_control(id,bucket,key,count,expires_at) VALUES(?,?,?,?,?)", (ident,bucket,key,1,datetime.fromtimestamp(expiry,timezone.utc).isoformat()))
            return True

class SQLRepositories:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db; self.abuse_control = SQLiteAbuseControl(db)
    def _commit(self) -> None: self.db.commit()
    def _audit(self, event: AuditEvent) -> None:
        self.db.execute("INSERT INTO audit_events(group_id,actor_user_id,request_id,action,entity_type,entity_id,metadata_json,occurred_at) VALUES(?,?,?,?,?,?,?,?)", (event.group_id,event.actor_user_id,event.request_id,event.action,event.entity_type,event.entity_id,json.dumps(event.metadata),_s(event.occurred_at)))
    def create_group(self, group_id: str, name: str, admin_user_id: str, now: datetime|None=None, *, event: AuditEvent|None=None, session: Any=None) -> None:
        now=now or _now(); c=session or self.db
        c.execute("INSERT INTO pool_groups VALUES(?,?,?,?,?)",(group_id,name,admin_user_id,_s(now),_s(now))); c.execute("INSERT INTO memberships VALUES(?,?,?,?,NULL)",(group_id,admin_user_id,"admin",_s(now)))
        if event: self._audit(event)
        if not session: self._commit()
    def create_password_user(self,user_id:str,username:str,password_hash:str,now:datetime|None=None)->dict[str,Any]:
        now=now or _now(); self.db.execute("INSERT INTO users(id,username,normalized_username,password_hash,created_at,updated_at) VALUES(?,?,?,?,?,?)",(user_id,username.strip(),username.strip().casefold(),password_hash,_s(now),_s(now))); self._commit(); return {"id":user_id,"username":username.strip(),"created_at":now}
    def find_user_by_username(self,username:str)->dict[str,Any]|None: return self._user(self.db.execute("SELECT * FROM users WHERE normalized_username=?",(username.strip().casefold(),)).fetchone(), True)
    def search_usernames(self,substring:str,limit:int=10)->list[dict[str,Any]]:
        """Return only bounded public username suggestions.

        The normalized column is used for matching so the application and
        registration uniqueness rules have the same case-folding semantics.
        No profile or email columns are selected for this autocomplete query.
        """
        needle = substring.strip().casefold()
        rows = self.db.execute(
            "SELECT username FROM users "
            "WHERE normalized_username IS NOT NULL AND instr(normalized_username, ?) > 0 "
            "ORDER BY normalized_username, username LIMIT ?",
            (needle, min(max(limit, 1), 25)),
        ).fetchall()
        return [{"username": row["username"]} for row in rows]
    def upsert_user(self,user_id:str,issuer:str,subject:str,email:str,display_name:str,avatar_url:str|None,*,now:datetime|None=None)->dict[str,Any]:
        now=now or _now(); self.db.execute("INSERT INTO users(id,google_issuer,google_subject,email,normalized_email,display_name,avatar_url,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(google_issuer,google_subject) DO UPDATE SET email=excluded.email,normalized_email=excluded.normalized_email,display_name=excluded.display_name,avatar_url=excluded.avatar_url,updated_at=excluded.updated_at",(user_id,issuer,subject,email,email.casefold(),display_name,avatar_url,_s(now),_s(now))); self._commit(); return self._user(self.db.execute("SELECT * FROM users WHERE google_issuer=? AND google_subject=?",(issuer,subject)).fetchone()) or {}
    def _user(self,row:Any, credentials:bool=False)->dict[str,Any]|None:
        if not row:return None
        d=dict(row); d["_id"]=d["id"]; d["created_at"]=_dt(d["created_at"]); d["updated_at"]=_dt(d["updated_at"]); return d
    def get_user(self,user_id:str)->dict[str,Any]|None:return self._user(self.db.execute("SELECT * FROM users WHERE id=?",(user_id,)).fetchone())
    def find_user_by_email(self,email:str)->dict[str,Any]|None:return self._user(self.db.execute("SELECT * FROM users WHERE normalized_email=?",(email.casefold(),)).fetchone())
    def create_session(self,session_id:str,user_id:str,token_hash:str,expires_at:datetime,*,now:datetime|None=None)->None:
        now=now or _now(); self.db.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?,?)",(session_id,user_id,token_hash,_s(now),_s(expires_at),None,_s(now))); self._commit()
    def get_active_session(self,token_hash:str,*,now:datetime|None=None)->dict[str,Any]|None:
        r=self.db.execute("SELECT * FROM sessions WHERE token_hash=? AND revoked_at IS NULL AND expires_at>?",(token_hash,_s(now or _now()))).fetchone()
        if not r:return None
        d=dict(r); d["_id"]=d["id"]; return d
    def get_session(self,session_id:str)->dict[str,Any]|None:
        r=self.db.execute("SELECT * FROM sessions WHERE id=?",(session_id,)).fetchone()
        if not r:return None
        d=dict(r); d["_id"]=d["id"]; return d
    def revoke_session(self,session_id:str,*,now:datetime|None=None)->bool:
        cur=self.db.execute("UPDATE sessions SET revoked_at=? WHERE id=? AND revoked_at IS NULL",(_s(now or _now()),session_id)); self._commit(); return cur.rowcount==1
    def request_hash(self,payload:Any)->str:return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
    def claim_idempotency(self,scope_key:str,principal:str,group_id:str|None,method:str,route:str,request_hash:str,expires_at:datetime,*,session:Any=None)->bool:
        c=session or self.db; now=_now(); c.execute("DELETE FROM idempotency WHERE expires_at<=?",(_s(now),))
        try:c.execute("INSERT INTO idempotency VALUES(?,?,?,?,?,?,?,?,?)",(scope_key,principal,group_id,method,route,request_hash,None,_s(now),_s(expires_at)))
        except sqlite3.IntegrityError:return False
        if not session:self._commit()
        return True
    def save_idempotency_response(self,scope_key:str,response:dict[str,Any],*,session:Any=None)->bool:
        c=session or self.db; cur=c.execute("UPDATE idempotency SET response_json=? WHERE scope_key=? AND response_json IS NULL",(json.dumps(response,default=str),scope_key));
        if not session:self._commit()
        return cur.rowcount==1
    def get_idempotency(self,scope_key:str,*,principal:str|None=None,group_id:str|None=None,method:str|None=None,route:str|None=None,now:datetime|None=None)->dict[str,Any]|None:
        r=self.db.execute("SELECT * FROM idempotency WHERE scope_key=? AND expires_at>?",(scope_key,_s(now or _now()))).fetchone()
        if not r:return None
        d=dict(r); d["response"]=json.loads(d.pop("response_json")) if d["response_json"] else None; return d
    def get_group(self,group_id:str)->dict[str,Any]|None:
        r=self.db.execute("SELECT * FROM pool_groups WHERE id=?",(group_id,)).fetchone()
        if not r:return None
        d=dict(r); d["members"]={x["user_id"]:dict(x) for x in self.db.execute("SELECT user_id,role,created_at,removed_at FROM memberships WHERE group_id=?",(group_id,))}; return d
    def list_groups_for_user(self,user_id:str,limit:int=100)->list[dict[str,Any]]:
        rows=self.db.execute("SELECT g.*,count(m2.user_id) member_count FROM pool_groups g JOIN memberships m ON m.group_id=g.id AND m.user_id=? AND m.removed_at IS NULL LEFT JOIN memberships m2 ON m2.group_id=g.id AND m2.removed_at IS NULL GROUP BY g.id ORDER BY g.created_at DESC LIMIT ?",(user_id,min(max(limit,1),100))).fetchall(); return [dict(r) for r in rows]
    def list_members(self,group_id:str,limit:int=25,cursor:str|None=None)->dict[str,Any]:
        rows = self.db.execute(
            "SELECT m.group_id,m.user_id,m.role,m.created_at,u.username "
            "FROM memberships m JOIN users u ON u.id=m.user_id "
            "WHERE m.group_id=? AND m.removed_at IS NULL "
            "ORDER BY m.created_at DESC,m.user_id DESC LIMIT ?",
            (group_id, min(max(limit, 1), 100)),
        ).fetchall()
        return {"items": [dict(r, created_at=_dt(r["created_at"])) for r in rows]}
    def add_member(self,group_id:str,user_id:str,role:str="member",*,event:AuditEvent|None=None,session:Any=None)->bool:
        c=session or self.db
        try:c.execute("INSERT INTO memberships VALUES(?,?,?,?,NULL)",(group_id,user_id,role,_s(_now())))
        except sqlite3.IntegrityError:return False
        if event:self._audit(event)
        if not session:self._commit()
        return True
    def remove_member(self,group_id:str,user_id:str,*,event:AuditEvent|None=None,session:Any=None)->bool:
        c=session or self.db; cur=c.execute("UPDATE memberships SET removed_at=? WHERE group_id=? AND user_id=? AND removed_at IS NULL",(_s(_now()),group_id,user_id));
        if cur.rowcount and event:self._audit(event)
        if not session:self._commit()
        return cur.rowcount==1
    def _pool(self,row:Any)->dict[str,Any]:
        d=dict(row); d["options"]=json.loads(d.pop("options_json")); d.update({k:(_dt(d[k]) if d.get(k) else None) for k in ("created_at","updated_at","opened_at","closed_at")}); d["answers"]={x["user_id"]:dict(x) for x in self.db.execute("SELECT user_id,option_id,submitted_at FROM answers WHERE pool_id=?",(d["id"],))}; return d
    def get_pool(self,group_id:str,pool_id:str,*,session:Any=None)->dict[str,Any]|None:
        r=(session or self.db).execute("SELECT * FROM pools WHERE group_id=? AND id=?",(group_id,pool_id)).fetchone(); return {"pools":{pool_id:self._pool(r)}} if r else None
    def create_pool(self,group_id:str,pool_id:str,question:str,options:list[PoolOption],*,event:AuditEvent|None=None,session:Any=None)->bool:
        now=_now(); c=session or self.db
        try:c.execute("INSERT INTO pools VALUES(?,?,?,?,?,?,?,?,?)",(pool_id,group_id,question,"draft",json.dumps([{"id":o.id,"label":o.label} for o in options]),None,None,_s(now),_s(now)))
        except sqlite3.IntegrityError:return False
        if event:self._audit(event)
        if not session:self._commit()
        return True
    def update_draft_pool(self,group_id:str,pool_id:str,question:str,options:list[PoolOption],*,event:AuditEvent|None=None,session:Any=None)->bool:
        c=session or self.db; cur=c.execute("UPDATE pools SET question=?,options_json=?,updated_at=? WHERE group_id=? AND id=? AND status='draft'",(question,json.dumps([{"id":o.id,"label":o.label} for o in options]),_s(_now()),group_id,pool_id));
        if cur.rowcount and event:self._audit(event)
        if not session:self._commit()
        return cur.rowcount==1
    def transition_pool(self,group_id:str,pool_id:str,expected:str,target:str,actor_user_id:str,event:AuditEvent,*,session:Any)->bool:
        now=_s(event.occurred_at); fields="status=?,updated_at=?"; args=[target,now]
        if target=="open":fields+=",opened_at=?";args.append(now)
        if target=="closed":fields+=",closed_at=?";args.append(now)
        args += [group_id, pool_id, group_id, actor_user_id, expected]
        cur=session.execute(f"UPDATE pools SET {fields} WHERE group_id=? AND id=? AND EXISTS(SELECT 1 FROM pool_groups WHERE id=? AND admin_user_id=?) AND status=?", args)
        if cur.rowcount:self._audit(event)
        return cur.rowcount==1
    def submit_answer(self,group_id:str,pool_id:str,user_id:str,option_id:str,event:AuditEvent,*,session:Any)->bool:
        try: session.execute("INSERT INTO answers VALUES(?,?,?,?)",(pool_id,user_id,option_id,_s(event.occurred_at)))
        except sqlite3.IntegrityError:return False
        valid=session.execute("SELECT 1 FROM pools p JOIN memberships m ON m.group_id=p.group_id WHERE p.id=? AND p.group_id=? AND p.status='open' AND m.user_id=? AND m.removed_at IS NULL AND EXISTS(SELECT 1 FROM json_each(p.options_json) WHERE json_extract(value,'$.id')=?)",(pool_id,group_id,user_id,option_id)).fetchone()
        if not valid:session.execute("DELETE FROM answers WHERE pool_id=? AND user_id=?",(pool_id,user_id));return False
        self._audit(event); return True
    def list_pools(self,group_id:str,status:str|None=None,limit:int=25,cursor:Cursor|None=None)->list[dict[str,Any]]:
        q="SELECT * FROM pools WHERE group_id=?";args=[group_id]
        if status:q+=" AND status=?";args.append(status)
        q+=" ORDER BY created_at DESC,id DESC LIMIT ?";args.append(min(max(limit,1),100)); return [{**self._pool(r),"group_id":group_id} for r in self.db.execute(q,args)]
    def results(self,group_id:str,pool_id:str)->dict[str,Any]|None:
        p=self.get_pool(group_id,pool_id)
        if not p or p["pools"][pool_id]["status"]!="closed":return None
        pool=p["pools"][pool_id]; counts={o["id"]:0 for o in pool["options"]}
        for a in pool["answers"].values():counts[a["option_id"]]=counts.get(a["option_id"],0)+1
        total=len(pool["answers"]); return {"pool_id":pool_id,"total_answers":total,"options":[{"option_id":o["id"],"label":o["label"],"count":counts[o["id"]],"percentage":counts[o["id"]]*100/total if total else 0} for o in pool["options"]]}
