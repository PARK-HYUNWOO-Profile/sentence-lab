import json
import os
import random
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

ROOT = Path(__file__).resolve().parent
DB_PATH = os.getenv("DATABASE_PATH", str(ROOT / "sentence_lab.db"))
app = FastAPI(title="Sentence Lab API", version="1.0.0")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

# Safe fallback pool is used if OPENAI_API_KEY is not configured or the API is unavailable.
FALLBACK = [
 {"s":"Birds fly.","a":1,"d":1,"why":"Birds(S) + fly(V)가 핵심 구조이며 필수 목적어나 보어 없이 문장이 완성됩니다.","parts":[["Birds","S"],["fly","V"]]},
 {"s":"The baby cried loudly.","a":1,"d":1,"why":"The baby(S) + cried(V)가 핵심입니다. loudly는 동사를 꾸미는 부사입니다.","parts":[["The baby","S"],["cried","V"],["loudly","부사"]]},
 {"s":"The soup smells delicious.","a":2,"d":1,"why":"The soup(S) + smells(V) + delicious(C). delicious는 주어의 상태를 설명하는 주격보어입니다.","parts":[["The soup","S"],["smells","V"],["delicious","C"]]},
 {"s":"Mina became a doctor.","a":2,"d":1,"why":"Mina(S) + became(V) + a doctor(C). a doctor는 주어 Mina의 정체를 설명합니다.","parts":[["Mina","S"],["became","V"],["a doctor","C"]]},
 {"s":"We watched the match.","a":3,"d":1,"why":"We(S) + watched(V) + the match(O). the match는 watched의 대상인 목적어입니다.","parts":[["We","S"],["watched","V"],["the match","O"]]},
 {"s":"The team solved the difficult problem quickly.","a":3,"d":2,"why":"The team(S) + solved(V) + the difficult problem(O)가 핵심입니다. quickly는 부사입니다.","parts":[["The team","S"],["solved","V"],["the difficult problem","O"],["quickly","부사"]]},
 {"s":"She taught the children English.","a":4,"d":2,"why":"She(S) + taught(V) + the children(IO) + English(DO). children은 받는 사람, English는 가르친 내용입니다.","parts":[["She","S"],["taught","V"],["the children","IO"],["English","DO"]]},
 {"s":"I sent my colleague the revised schedule yesterday.","a":4,"d":3,"why":"I(S) + sent(V) + my colleague(IO) + the revised schedule(DO)가 핵심입니다. yesterday는 부사입니다.","parts":[["I","S"],["sent","V"],["my colleague","IO"],["the revised schedule","DO"],["yesterday","부사"]]},
 {"s":"The news made everyone anxious.","a":5,"d":2,"why":"The news(S) + made(V) + everyone(O) + anxious(OC). anxious는 everyone의 상태를 설명하는 목적격보어입니다.","parts":[["The news","S"],["made","V"],["everyone","O"],["anxious","OC"]]},
 {"s":"The committee considered the proposal unnecessarily complicated.","a":5,"d":3,"why":"The committee(S) + considered(V) + the proposal(O) + unnecessarily complicated(OC). complicated는 목적어의 성질을 설명합니다.","parts":[["The committee","S"],["considered","V"],["the proposal","O"],["unnecessarily complicated","OC"]]},
 {"s":"After the long meeting, the guests remained silent.","a":2,"d":3,"why":"주절은 the guests(S) + remained(V) + silent(C)입니다. 문장 앞 after 구는 부사구입니다.","parts":[["the guests","S"],["remained","V"],["silent","C"]]},
 {"s":"The guide showed the visitors a hidden courtyard.","a":4,"d":3,"why":"The guide(S) + showed(V) + the visitors(IO) + a hidden courtyard(DO). 목적어 두 개가 받는 사람과 보여 준 대상을 나타냅니다.","parts":[["The guide","S"],["showed","V"],["the visitors","IO"],["a hidden courtyard","DO"]]},
 {"s":"We found the instructions confusing at first.","a":5,"d":3,"why":"We(S) + found(V) + the instructions(O) + confusing(OC). confusing은 instructions의 성격을 설명합니다.","parts":[["We","S"],["found","V"],["the instructions","O"],["confusing","OC"]]},
 {"s":"The old engine suddenly stopped.","a":1,"d":2,"why":"The old engine(S) + stopped(V)가 핵심 구조입니다. suddenly는 부사입니다.","parts":[["The old engine","S"],["stopped","V"],["suddenly","부사"]]},
 {"s":"Her explanation sounded perfectly reasonable.","a":2,"d":3,"why":"Her explanation(S) + sounded(V) + reasonable(C). perfectly는 reasonable을 꾸미는 부사입니다.","parts":[["Her explanation","S"],["sounded","V"],["perfectly reasonable","C"]]},
 {"s":"The researcher analyzed the results in detail.","a":3,"d":3,"why":"The researcher(S) + analyzed(V) + the results(O)가 핵심입니다. in detail은 부사구입니다.","parts":[["The researcher","S"],["analyzed","V"],["the results","O"],["in detail","부사구"]]},
 {"s":"The director appointed Lena team leader.","a":5,"d":3,"why":"The director(S) + appointed(V) + Lena(O) + team leader(OC). team leader는 Lena의 역할을 설명합니다.","parts":[["The director","S"],["appointed","V"],["Lena","O"],["team leader","OC"]]},
 {"s":"He offered his colleague a practical solution.","a":4,"d":2,"why":"He(S) + offered(V) + his colleague(IO) + a practical solution(DO). colleague는 받는 사람입니다.","parts":[["He","S"],["offered","V"],["his colleague","IO"],["a practical solution","DO"]]}
]

def connect():
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
            learner TEXT NOT NULL, teacher TEXT NOT NULL DEFAULT '',
            score INTEGER NOT NULL, level TEXT NOT NULL, payload TEXT NOT NULL)""")
        con.execute("""CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT, teacher TEXT NOT NULL,
            learner TEXT NOT NULL, feedback TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(teacher, learner))""")
init_db()

class ResultIn(BaseModel):
    date: str | None = None
    learner: str = Field(min_length=1, max_length=80)
    teacher: str = Field(default="", max_length=80)
    score: int = Field(ge=0, le=10)
    level: str = Field(pattern="^(초급|중급|고급)$")
    questions: list[dict[str, Any]] = Field(min_length=10, max_length=10)

class FeedbackIn(BaseModel):
    teacher: str = Field(min_length=1, max_length=80)
    learner: str = Field(min_length=1, max_length=80)
    feedback: str = Field(max_length=5000)

@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")

@app.get("/api/health")
def health():
    return {"ok": True, "gpt_enabled": bool(os.getenv("OPENAI_API_KEY"))}

def generate_with_gpt(difficulty: int, exclude: list[str]):
    if not os.getenv("OPENAI_API_KEY") or OpenAI is None:
        return None
    try:
        client = OpenAI()
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0.9,
            response_format={"type": "json_object"},
            messages=[
                {"role":"system","content":(
                    "You are an expert English grammar teacher. Generate exactly one natural English sentence "
                    "whose main clause has exactly one intended traditional English sentence pattern, 1-5. "
                    "Return JSON keys s (sentence), a (integer 1-5), d (difficulty 1-3), why (brief Korean explanation), "
                    "parts (array of [exact phrase, grammatical label] for core constituents). Labels: S,V,O,C,IO,DO,OC,부사,부사구. "
                    "Be careful: distinguish linking verbs and subject complements, ditransitive verbs, and object complements. "
                    "Do not count optional adverbials as required complements. Keep grammar unambiguous. "
                    "Difficulty 1 simple; 2 includes adverbs/longer phrases; 3 includes subordinate/introductory phrases or modifiers. "
                    "Only output valid JSON."
                )},
                {"role":"user","content":f"Generate one new sentence. Difficulty {max(1,min(3,difficulty))}. Avoid these exact sentences: {exclude[-30:]}. Make the correct pattern random across 1-5. Return JSON only."}
            ],
        )
        data = json.loads(response.choices[0].message.content or "{}")
        if not isinstance(data.get("s"), str) or not 1 <= int(data.get("a", 0)) <= 5:
            return None
        data["a"] = int(data["a"])
        data["d"] = max(1, min(3, int(data.get("d", difficulty))))
        data["parts"] = data.get("parts", [])
        data["why"] = str(data.get("why", "문장 성분의 기능을 확인하세요."))
        return data
    except Exception:
        return None

@app.get("/api/question")
def question(difficulty: int = Query(1, ge=1, le=3), exclude: str = ""):
    excluded = [x for x in exclude.split("|") if x]
    generated = generate_with_gpt(difficulty, excluded)
    if generated and generated["s"] not in excluded:
        return generated
    candidates = [x for x in FALLBACK if x["d"] <= difficulty and x["s"] not in excluded]
    if not candidates:
        candidates = [x for x in FALLBACK if x["s"] not in excluded] or FALLBACK
    return random.choice(candidates)

@app.post("/api/results")
def save_result(body: ResultIn):
    now = datetime.now(timezone.utc).isoformat()
    payload = body.model_dump()
    payload["date"] = body.date or datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    with connect() as con:
        cur = con.execute(
            "INSERT INTO results(created_at, learner, teacher, score, level, payload) VALUES(?,?,?,?,?,?)",
            (now, body.learner, body.teacher, body.score, body.level, json.dumps(payload, ensure_ascii=False))
        )
        payload["id"] = cur.lastrowid
    return payload

@app.get("/api/results")
def list_results(teacher: str = "", learner: str = ""):
    # Beta mode: records are filtered by nickname, not account authentication.
    query = "SELECT payload, id FROM results WHERE 1=1"
    params: list[str] = []
    if teacher:
        query += " AND teacher=?"; params.append(teacher)
    if learner:
        query += " AND learner=?"; params.append(learner)
    query += " ORDER BY id DESC LIMIT 500"
    with connect() as con:
        rows = con.execute(query, params).fetchall()
    output = []
    for row in rows:
        item = json.loads(row["payload"]); item["id"] = row["id"]; output.append(item)
    return output

@app.post("/api/feedback")
def save_feedback(body: FeedbackIn):
    now = datetime.now(timezone.utc).isoformat()
    with connect() as con:
        con.execute("""INSERT INTO feedback(teacher, learner, feedback, updated_at) VALUES(?,?,?,?)
            ON CONFLICT(teacher, learner) DO UPDATE SET feedback=excluded.feedback, updated_at=excluded.updated_at""",
            (body.teacher, body.learner, body.feedback, now))
    return {"ok": True, "updated_at": now}

@app.get("/api/feedback")
def get_feedback(teacher: str, learner: str):
    with connect() as con:
        row = con.execute("SELECT feedback, updated_at FROM feedback WHERE teacher=? AND learner=?", (teacher, learner)).fetchone()
    return dict(row) if row else {"feedback": "", "updated_at": None}
