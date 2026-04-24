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
    return {"status": "ok", "supabase_url_set": bool(URL), "key_set": bool(KEY)}

@app.get("/")
def root():
    return {"message": "KPO Ops Intelligence API is running"}
