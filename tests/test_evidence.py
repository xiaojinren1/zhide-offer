"""Real account-scoped SQLite/API import regression tests; no model calls."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"backend"))
from fastapi.testclient import TestClient
from core import accounts
from main import app

class EvidenceTests(unittest.TestCase):
 def setUp(self):
  folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
  patcher=patch.object(accounts,"DATABASE_PATH",Path(folder.name)/"db.sqlite3");patcher.start();self.addCleanup(patcher.stop)
  self.client=TestClient(app,headers={"X-Requested-With":"XMLHttpRequest"});self.addCleanup(self.client.close)
  self.client.post("/api/auth/register",json={"username":"library_a","password":"demo-only-12345"})
  self.uid=self.client.get("/api/auth/me").json()["user"]["id"]
  self.profile={"name":"虚构","experiences":[{"kind":"project","name":"校园报名平台","role":"成员","period":"2025.01—2025.06","actions":["访谈用户"],"results":["转化率提升20%"],"skills":[]}],"education":[],"skills":[],"raw_text":"原始证据","user_confirmed":True}
 def body(self):return {"expected_user_id":self.uid,"profile":copy.deepcopy(self.profile),"source_name":"虚构材料"}
 def bank(self):return self.client.get("/api/library").json()
 def apply(self,body=None,choice=None,revision=None):
  return self.client.post("/api/library/import",json={**(body or self.body()),"facts_confirmed":True,"revision":self.bank()["revision"] if revision is None else revision,"choices":choice or [{"action":"new"}]})
 def test_repeated_upload_and_cosmetic_changes_skip(self):
  self.assertEqual(self.apply().status_code,200)
  self.profile["experiences"][0]["actions"]=["访谈 用户。"]
  preview=self.client.post("/api/library/preview",json=self.body()).json()
  self.assertEqual(preview["items"][0]["status"],"same")
  self.assertEqual(self.apply().json()["changed"],0)
  self.assertEqual(len(self.bank()["cards"]),1)
 def test_field_selection_numbers_history_and_recycle(self):
  self.apply();old=self.bank();card=old["cards"][0]
  self.profile["experiences"][0]["actions"].append("绘制流程图")
  self.profile["experiences"][0]["results"]=["转化率提升30%"]
  result=self.apply(choice=[{"action":"merge","target":card["id"],"fields":["actions"]}])
  self.assertEqual(result.status_code,200,result.text)
  latest=self.bank()["cards"][0]
  self.assertEqual(latest["results"],["转化率提升20%"])
  self.assertIn("绘制流程图",latest["actions"])
  self.assertEqual(len(latest["history"]),2)
  self.assertEqual(len(self.bank()["sources"]),2)
  for action in ["delete","restore","revert"]:
   response=self.client.post("/api/library/"+card["id"]+"/action",json={"expected_user_id":self.uid,"revision":self.bank()["revision"],"action":action,"version":0})
   self.assertEqual(response.status_code,200,response.text)
  self.assertEqual(self.bank()["cards"][0]["actions"],["访谈用户"])
 def test_batch_dedup_and_revision_protection(self):
  self.profile["experiences"]*=2
  response=self.apply(choice=[{"action":"new"},{"action":"new"}])
  self.assertEqual(response.json()["changed"],1)
  self.assertEqual(self.apply(revision=0).status_code,409)
 def test_education_discards_descriptions(self):
  self.profile["experiences"][0]["kind"]="education"
  self.apply();card=self.bank()["cards"][0]
  self.assertEqual([card[k] for k in ["actions","results","skills"]],[[],[],[]])
  self.assertEqual(self.bank()["sources"][0]["profile"]["raw_text"],"原始证据")
 def test_account_confirmation_and_csrf(self):
  body=self.body();body["profile"]["user_confirmed"]=False
  self.assertEqual(self.apply(body=body).status_code,422)
  body=self.body();body["expected_user_id"]="other"
  self.assertEqual(self.apply(body=body).status_code,409)
  self.apply();card=self.bank()["cards"][0]
  other=TestClient(app,headers={"X-Requested-With":"XMLHttpRequest"});self.addCleanup(other.close)
  other.post("/api/auth/register",json={"username":"library_b","password":"demo-only-12345"})
  uid=other.get("/api/auth/me").json()["user"]["id"]
  self.assertEqual(other.get("/api/library").json()["cards"],[])
  response=other.post("/api/library/import",json={**self.body(),"expected_user_id":uid,"facts_confirmed":True,"revision":0,"choices":[{"action":"merge","target":card["id"],"fields":["actions"]}]})
  self.assertEqual(response.status_code,422)
  self.client.headers.pop("X-Requested-With")
  self.assertEqual(self.apply().status_code,403)
 def test_legacy_migration_keeps_original(self):
  saved=self.client.post("/api/profiles/save",json={"name":"旧材料","profile":self.profile}).json()["id"]
  body={"expected_user_id":self.uid,"legacy_id":saved,"source_name":"旧材料"}
  self.assertEqual(self.client.post("/api/library/preview",json=body).status_code,200)
  self.assertEqual(self.apply(body=body).status_code,200)
  self.assertEqual(self.client.get("/api/profiles/"+saved).status_code,200)
  self.assertIn(saved,self.bank()["migrated"])
 def test_same_name_ambiguous_and_new_project_allowed(self):
  self.apply();self.profile["experiences"][0]["period"]="2026.01—2026.02"
  preview=self.client.post("/api/library/preview",json=self.body()).json()
  self.assertEqual(preview["items"][0]["status"],"review")
  self.apply();self.assertEqual(len(self.bank()["cards"]),2)

 def test_changed_numbers_require_explicit_replacement(self):
  self.apply();card=self.bank()["cards"][0]
  self.profile["experiences"][0]["results"]=["转化率提升30%"]
  preview=self.client.post("/api/library/preview",json=self.body()).json()
  self.assertIn("results",preview["items"][0]["candidates"][0]["conflicts"])
  choice={"action":"merge","target":card["id"],"fields":["results"]}
  self.assertEqual(self.apply(choice=[choice]).status_code,422)
  self.assertEqual(self.bank()["cards"][0]["results"],["转化率提升20%"])
  choice["replace_fields"]=["results"]
  self.assertEqual(self.apply(choice=[choice]).status_code,200)
  self.assertEqual(self.bank()["cards"][0]["results"],["转化率提升30%"])
  self.assertEqual(self.bank()["cards"][0]["history"][0]["facts"]["results"],["转化率提升20%"])
 def test_parser_cleans_education_descriptions(self):
  from engine.resume_parser import _fill_periods
  from engine.models import Experience
  exp=Experience(kind="education",name="学校",role="本科",period="2022—2026",actions=["不要作为教育描述"],results=["描述"],skills=["描述"])
  result=_fill_periods([exp])[0]
  self.assertEqual([result.actions,result.results,result.skills],[[],[],[]])

if __name__=="__main__":unittest.main()
