"""Training pipeline for RepoVue XGBoost Code Analysis Backup Models."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure backend root is on sys.path
backend_root = Path(__file__).resolve().parents[3]
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from app.logging_config import get_logger
from app.services.ml_backup.model import FallbackMLBundle

log = get_logger(__name__)

# Sample dataset mapping code snippets -> (category_id, severity_score, confidence)
# category_id: 0: clean, 1: security, 2: logical_bug, 3: performance, 4: architecture
# severity_score: 1.0 (low), 2.0 (medium), 3.0 (high), 4.0 (critical)
# confidence: 0.50 - 0.95

TRAINING_DATA = [
    # ---- 0: CLEAN CODE ----
    ("""def calculate_total(items: list[dict], tax_rate: float = 0.05) -> float:
    subtotal = sum(item['price'] * item['quantity'] for item in items)
    return round(subtotal * (1 + tax_rate), 2)""", 0, 0.0, 0.90),

    ("""async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()""", 0, 0.0, 0.92),

    ("""class HealthChecker:
    def __init__(self, endpoint: str):
        self.endpoint = endpoint
    async def ping(self) -> bool:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(self.endpoint)
            return resp.status_code == 200""", 0, 0.0, 0.88),

    ("""def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[^a-zA-Z0-9_.-]', '_', name)
    return cleaned[:100]""", 0, 0.0, 0.95),

    ("""from pydantic import BaseModel, Field
class UserCreate(BaseModel):
    email: str = Field(..., max_length=255)
    full_name: str | None = None
    role: str = 'user'""", 0, 0.0, 0.94),

    ("""def binary_search(arr: list[int], target: int) -> int:
    low, high = 0, len(arr) - 1
    while low <= high:
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1""", 0, 0.0, 0.95),

    # ---- 1: SECURITY ----
    ("""def search_users(cursor, search_term: str):
    query = f"SELECT * FROM users WHERE username = '{search_term}'"
    return cursor.execute(query).fetchall()""", 1, 4.0, 0.95),

    ("""app.get('/run-cmd')
def run_command(command: str):
    subprocess.call(f"ping {command}", shell=True)
    return {"status": "executed"}""", 1, 3.8, 0.95),

    ("""def run_dynamic(code: str):
    result = eval(code)
    return result""", 1, 3.5, 0.92),

    ("""def load_payload(raw_bytes: bytes):
    data = pickle.loads(raw_bytes)
    return data""", 1, 3.7, 0.94),

    ("""AWS_SECRET_KEY = "AKIAIOSFODNN7EXAMPLEsecretkey12345678"
DATABASE_PASSWORD = "SuperSecretPassword123!" """, 1, 3.4, 0.90),

    ("""def fetch_internal_data(url: str):
    response = requests.get(url, verify=False)
    return response.json()""", 1, 3.2, 0.88),

    ("""def hash_user_password(password: str) -> str:
    return hashlib.md5(password.encode()).hexdigest()""", 1, 2.8, 0.85),

    ("""def decode_auth_token(token: str):
    return jwt.decode(token, options={"verify_signature": False})""", 1, 4.0, 0.95),

    ("""app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"]
)""", 1, 2.5, 0.82),

    # ---- 2: LOGICAL BUGS ----
    ("""def process_payment(amount: float, card: dict):
    try:
        charge(card, amount)
    except:
        pass""", 2, 3.2, 0.88),

    ("""def get_customer_discount(user):
    if user.is_vip == True:
        discount = 0.2
    elif user.is_vip == False:
        discount = 0.05
    return discount * user.cart_total""", 2, 2.6, 0.82),

    ("""def append_to_cache(item: str, cache: list = []):
    cache.append(item)
    return cache""", 2, 2.4, 0.85),

    ("""def compute_ratios(values: list[float]) -> list[float]:
    base = values[0]
    return [v / base for v in values]""", 2, 2.5, 0.80),

    ("""def drain_queue(q: Queue):
    while True:
        item = q.get()
        print(item)""", 2, 3.0, 0.85),

    ("""def calculate_mean(values: list[float]) -> float:
    try:
        return sum(values) / len(values)
    except Exception:
        ...""", 2, 2.2, 0.82),

    # ---- 3: PERFORMANCE ----
    ("""def find_duplicates(items: list[int]) -> list[int]:
    dupes = []
    for i in range(len(items)):
        for j in range(len(items)):
            if i != j and items[i] == items[j] and items[i] not in dupes:
                dupes.append(items[i])
    return dupes""", 3, 2.8, 0.89),

    ("""async def sync_notifications(users: list[User]):
    for user in users:
        time.sleep(1.5)
        send_email(user.email)""", 3, 3.2, 0.91),

    ("""def load_entire_database_table(session):
    records = session.query(AuditLog).all()
    filtered = [r for r in records if r.status == 'FAIL']
    return filtered[:10]""", 3, 3.0, 0.87),

    ("""def build_html_table(rows: list[list[str]]) -> str:
    html = ""
    for row in rows:
        html += "<tr>"
        for col in row:
            html += f"<td>{col}</td>"
        html += "</tr>"
    return html""", 3, 2.0, 0.80),

    # ---- 4: ARCHITECTURE ----
    ("""global_config = {}
def update_settings(new_cfg):
    global global_config
    global_config.update(new_cfg)""", 4, 2.6, 0.84),

    ("""from app.models import *
from app.views import *
from app.utils import *
from app.helpers import *""", 4, 2.4, 0.85),

    ("""# TODO: Fix this hack before shipping to production
# FIXME: Memory leak occurs here under load
def workaround_handler():
    pass""", 4, 1.8, 0.80),

    ("""class GodManager:
    def parse_http(self): pass
    def execute_sql(self): pass
    def render_react(self): pass
    def send_smtp_email(self): pass
    def generate_pdf(self): pass
    def run_backup(self): pass""", 4, 3.0, 0.86),
]


def train_and_save_model(output_path: str | Path | None = None) -> Path:
    if output_path is None:
        base_dir = Path(__file__).resolve().parent
        output_path = base_dir / "models" / "xgboost_fallback.joblib"

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    texts = [item[0] for item in TRAINING_DATA]
    categories = [item[1] for item in TRAINING_DATA]
    severities = [item[2] for item in TRAINING_DATA]
    confidences = [item[3] for item in TRAINING_DATA]

    log.info("training_xgboost_fallback_model", samples=len(texts))
    bundle = FallbackMLBundle()
    bundle.fit(texts, categories, severities, confidences)
    bundle.save(output_path)

    # Sanity check
    test_sample = "def query(term): return db.execute(f'SELECT * FROM x WHERE id={term}')"
    pred = bundle.predict([test_sample])[0]
    log.info("model_verification_successful", category=pred["category"], severity=pred["severity"], confidence=pred["confidence"])

    return output_path


if __name__ == "__main__":
    path = train_and_save_model()
    print(f"Model successfully trained and saved to: {path}")
