from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import httpx, os

load_dotenv()

app = FastAPI()

URL = os.getenv("SUPABASE_URL", "")
KEY = os.getenv("SUPABASE_KEY", "")

HEADERS = {
    "apikey": KEY,
    "Authorization": f"Bearer {KEY}",
    "Content-Type": "application/json"
}

app.add_middleware(CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)

@app.get("/")
def root():
    return {"message": "KPO Ops Intelligence API is running"}

@app.get("/health")
def health():
    return {"status": "ok"}
def flag_stuck_reviews():
    cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
    tasks = httpx.get(f"{URL}/rest/v1/tasks",
        headers=HEADERS,
        params={"status":"eq.with_reviewer",
                "updated_at":f"lt.{cutoff}",
                "select":"id,update_token,title,clients(name),staff(name)"})
    for t in tasks.json():
        httpx.patch(f"{URL}/rest/v1/tasks",
            headers={**HEADERS,"Prefer":"return=minimal"},
            params={"id":f"eq.{t['id']}"},
            json={"reviewer_flag": True})
        send_teams_alert(
            t["staff"]["name"], t["title"],
            t["clients"]["name"], t["update_token"])

scheduler = BackgroundScheduler()
scheduler.add_job(flag_stuck_reviews, 'interval', hours=1)
scheduler.start()
@app.post("/tasks")
def create_task(
    client_id: str, staff_id: str,
    reviewer_id: str, title: str,
    due_date: str, jurisdiction: str
):
    import secrets
    res = httpx.post(f"{URL}/rest/v1/tasks",
        headers={**HEADERS,"Prefer":"return=representation"},
        json={
            "client_id": client_id,
            "staff_id": staff_id,
            "reviewer_id": reviewer_id,
            "title": title,
            "due_date": due_date,
            "jurisdiction": jurisdiction,
            "status": "not_started",
            "update_token": secrets.token_hex(16),
            "reviewer_flag": False
        })
    return res.json()
