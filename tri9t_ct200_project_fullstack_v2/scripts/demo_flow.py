"""End-to-end API smoke flow. Start the API first: uvicorn app.main:app --reload."""
import json, urllib.request, urllib.error, time

BASE="http://127.0.0.1:8000"
def get(path):
    with urllib.request.urlopen(BASE+path) as r: return json.loads(r.read())
def post(path, data=None):
    req=urllib.request.Request(BASE+path, data=json.dumps(data).encode() if data is not None else b"",
      headers={"Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req) as r: return json.loads(r.read())
print("Ingest v1:", post("/documents/ct200/ingest/sample-v1"))
print("Ingest v2:", post("/documents/ct200/ingest/sample-v2"))
print("Top-level sections:", json.dumps(get("/documents/ct200/sections"), indent=2)[:2000])
hits=get("/documents/ct200/search?q=Battery&version=1")["results"]
if not hits: raise SystemExit("No battery section found; inspect parser output.")
selection=post("/selections", {"name":"Battery QA","node_ids":[hits[0]["id"]]})
print("Pinned selection:", selection)
generated=post(f"/selections/{selection['selection_id']}/generate")
print("Generated cases:", json.dumps(generated,indent=2))
print("Retrieved generation with staleness:", json.dumps(get(f"/generations/{generated['generation_id']}"),indent=2))
