"""Test-user and Mail.tm helpers; secrets are never logged."""
from __future__ import annotations
import json, os
from pathlib import Path
from typing import Any
import httpx

class TestUserStore:
    def __init__(self, path: str="qa-users.json"):
        self.path=Path(path)
    def load(self)->list[dict[str,Any]]:
        if not self.path.exists(): return []
        return json.loads(self.path.read_text(encoding="utf-8"))
    def save(self, users:list[dict[str,Any]])->None:
        self.path.write_text(json.dumps(users,indent=2),encoding="utf-8")

class MailTmClient:
    """Creates disposable Mail.tm accounts and polls inboxes."""
    def __init__(self, base_url: str="https://api.mail.tm", timeout: float=20):
        self.base_url=base_url.rstrip("/")
        self.timeout=timeout
    async def create_account(self, address: str, password: str)->dict[str,Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r=await c.post(f"{self.base_url}/accounts",json={"address":address,"password":password})
            r.raise_for_status(); return r.json()
    async def token(self, address:str,password:str)->str:
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r=await c.post(f"{self.base_url}/token",json={"address":address,"password":password})
            r.raise_for_status(); return r.json()["token"]
    async def messages(self, token:str)->list[dict[str,Any]]:
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r=await c.get(f"{self.base_url}/messages",headers={"Authorization":f"Bearer {token}"})
            r.raise_for_status(); return r.json().get("hydra:member",[])
    async def wait_for_message(self, token:str, timeout:int=90, interval:float=3)->dict[str,Any]|None:
        import asyncio
        end=asyncio.get_running_loop().time()+timeout
        while asyncio.get_running_loop().time()<end:
            msgs=await self.messages(token)
            if msgs: return msgs[0]
            await asyncio.sleep(interval)
        return None
    async def read_message(self, token:str, message_id:str)->dict[str,Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r=await c.get(f"{self.base_url}/messages/{message_id}",headers={"Authorization":f"Bearer {token}"})
            r.raise_for_status(); return r.json()
