import json
import logging
import os
import re
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

def load_dotenv(path=".env"):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
ALLOWED_CHAT_ID = int(os.getenv("ALLOWED_CHAT_ID", "-3811673849"))
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
GEMINI_AUTH_MODE = os.getenv("GEMINI_AUTH_MODE", "key").strip().lower()
CHAT_RATE_LIMIT_COUNT = int(os.getenv("CHAT_RATE_LIMIT_COUNT", "8"))
CHAT_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("CHAT_RATE_LIMIT_WINDOW_SECONDS", "60"))
REPORT_RATE_LIMIT_COUNT = int(os.getenv("REPORT_RATE_LIMIT_COUNT", "5"))
REPORT_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("REPORT_RATE_LIMIT_WINDOW_SECONDS", "300"))
AI_TIMEOUT_SECONDS = int(os.getenv("AI_TIMEOUT_SECONDS", "30"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
REPORT_MODE = "report_mode"
REPORT_DRAFT = "report_draft"
LIMIT_MESSAGE = "bugünlük bukadar sonra tekrar dene (limit bitti)"

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format="%(asctime)s %(levelname)s %(message)s")

URL_RE = re.compile(r"https?://[^\s<>'\")]+|(?:GET|POST|PUT|PATCH|DELETE)\s+/[\w./:?=&%+\-{}]+", re.I)
SEVERITY_RE = re.compile(r"\b(low|medium|med|high|critical|kritik|düşük|dusuk|orta|yüksek|yuksek)\b", re.I)
VULNERABILITY_PATTERNS = {
    "XSS": ("xss", "cross site scripting", "cross-site scripting", "stored xss", "reflected xss", "dom xss"),
    "SQLi": ("sqli", "sql injection", "sql enjeksiyon", "blind sql", "union select"),
    "IDOR": ("idor", "insecure direct object", "yetkisiz erişim", "yetkisiz erisim"),
    "SSRF": ("ssrf", "server side request forgery"),
    "RCE": ("rce", "remote code execution", "komut çalıştırma", "komut calistirma"),
    "CSRF": ("csrf", "cross site request forgery"),
    "Open Redirect": ("open redirect", "açık yönlendirme", "acik yonlendirme"),
    "File Upload": ("file upload", "dosya yükleme", "dosya yukleme", "unrestricted upload"),
    "LFI": ("lfi", "local file inclusion"),
    "XXE": ("xxe", "xml external entity"),
    "Auth Bypass": ("auth bypass", "authentication bypass", "kimlik doğrulama atlatma", "login bypass"),
    "Access Control": ("access control", "broken access", "authorization", "yetkilendirme"),
}
TRIGGER_WORDS = (
    "tetik", "nasıl", "nasil", "adım", "adim", "step", "reproduce", "payload", "request",
    "istek", "parametre", "parameter", "gönder", "gonder", "çalış", "calis", "endpoint", "body", "header", "cookie", "poc"
)
IMPACT_WORDS = (
    "etki", "risk", "impact", "account takeover", "ato", "veri", "data", "sızıntı", "sizinti",
    "unauthorized", "yetkisiz", "session", "token", "admin", "rce", "hesap", "müşteri", "musteri",
    "kişisel", "kisisel", "bypass"
)

CYBER_SYSTEM_PROMPT = """
Sen 0xVault ekibi için özel üretilmiş profesyonel bir siber güvenlik asistanısın.
Kimliğin: 0xVault Cyber Security Bot.
Yanıt dilini kullanıcının diline göre seç, Türkçe yazıyorsa Türkçe cevap ver.
Sadece siber güvenlik, bug bounty, güvenli kod, savunma, analiz, raporlama ve 0xVault ekibiyle ilgili makul sohbetlere cevap ver.
Konu dışı sorularda kibarca bu botun sadece 0xVault siber güvenlik görevleri için çalıştığını söyle.
Yetkisiz zarar verme, kötü amaçlı yazılım, kimlik bilgisi hırsızlığı, kalıcılık, kaçınma veya gerçek hedeflere saldırı talimatı verme.
Yasal bug bounty ve savunma amaçlı bağlamda net, uygulanabilir ve güvenli cevap üret.
Kısa ama eksiksiz, profesyonel ve doğal cevap ver.
""".strip()

REPORT_SYSTEM_PROMPT = """
Sen 0xVault ekibi için çalışan kıdemli bug bounty rapor yazım asistanısın.
Verilen ham bulgudan profesyonel, kesin, abartısız ve gönderime hazır rapor üret.
Eksik bilgi uydurma. Kullanıcının verdiği kanıtı koru. Risk ve etkiyi netleştir.
Yanıtı kullanıcının dilinde yaz fakat bölüm etiketlerini aşağıdaki formatta birebir koru.
Gereksiz markdown süsü, kod bloğu veya ekstra başlık kullanma.
Rapor mutlaka şu sırada ve şu etiketlerle yazılacak:
Title:
Açıklama:
Severity:
Etkilenen URL/Endpoint:
Açık Türü:
Teknik Detay:
Yeniden Üretim Adımları:
Etki/Risk:
Kanıt/PoC:
Önerilen Çözüm:
Doğrulama Notları:
""".strip()

HELP_TR = """
0xVault Cyber Security Bot komutları:

/chat <mesaj>
Siber güvenlik, bug bounty, güvenli kod ve savunma odaklı sorulara cevap verir.

/report
Bug bounty raporu oluşturma modunu başlatır. Zorunlu bilgiler: Açık türü, etkilenen URL veya endpoint, nasıl tetiklendiği, etki/risk ve severity.

/exitreport
Sadece rapor modundan çıkar.

/cancel
Aktif işlemleri ve geçici durumu iptal eder.

/help
Bu yardım ekranını gösterir.

Bot sadece yetkili 0xVault grup içinde çalışır ve konu dışı soruları yanıtlamaz.
""".strip()

REPORT_INTRO_TR = """
Rapor modunu başlattım. Bulguyu tek mesajda yaz.

Zorunlu bilgiler:
Açık türü (XSS, SQLi, IDOR...)
Etkilenen URL veya endpoint
Nasıl tetikleniyor
Etki/Risk (ne yapılabilir)
Severity (Low/Medium/High/Critical)

Çıkmak için /exitreport, her şeyi durdurmak için /cancel yaz.
""".strip()

user_state = defaultdict(dict)
rate_events = defaultdict(deque)

class AiLimitError(Exception):
    pass

class AiServiceError(Exception):
    pass

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in {"/", "/health"}:
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, *args):
        return

def start_health_server():
    port = int(os.getenv("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    Thread(target=server.serve_forever, daemon=True).start()
    logging.info("Health server started on port %s", port)

def http_json(url, payload=None, headers=None, timeout=35):
    headers = headers or {}
    if payload is None:
        request = urllib.request.Request(url, headers=headers, method="GET")
    else:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(body)
        except Exception:
            data = {"raw": body}
        return error.code, data

def telegram(method, payload=None, retries=3):
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            status, data = http_json(f"{BASE_URL}/{method}", payload, timeout=60)
            if status >= 400 or not data.get("ok", False):
                logging.warning("Telegram API error %s %s", status, data)
            return data
        except Exception as exc:
            last_error = exc
            wait_seconds = min(10, attempt * 2)
            logging.warning("Telegram API temporary error method=%s attempt=%s/%s error=%s", method, attempt, retries, exc)
            time.sleep(wait_seconds)
    raise RuntimeError(f"Telegram API failed after retries: {last_error}")

def send_message(chat_id, text, reply_to=None):
    text = text.strip() or "Tamam."
    chunks = []
    while len(text) > 3900:
        split_at = text.rfind("\n", 0, 3900)
        if split_at < 1500:
            split_at = 3900
        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()
    if text:
        chunks.append(text)
    for chunk in chunks:
        payload = {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True}
        if reply_to:
            payload["reply_to_message_id"] = reply_to
        telegram("sendMessage", payload)

def allow_rate(user_id, bucket, limit, window_seconds):
    now = time.monotonic()
    key = (user_id, bucket)
    events = rate_events[key]
    while events and now - events[0] >= window_seconds:
        events.popleft()
    if len(events) >= limit:
        retry_after = int(window_seconds - (now - events[0])) + 1
        return False, max(retry_after, 1)
    events.append(now)
    return True, 0

def clear_user(user_id):
    user_state.pop(user_id, None)
    for key in list(rate_events.keys()):
        if key[0] == user_id:
            rate_events.pop(key, None)

def normalize_severity(value):
    if not value:
        return None
    mapping = {
        "low": "Low", "düşük": "Low", "dusuk": "Low",
        "medium": "Medium", "med": "Medium", "orta": "Medium",
        "high": "High", "yüksek": "High", "yuksek": "High",
        "critical": "Critical", "kritik": "Critical",
    }
    return mapping.get(value.lower(), value.title())

def detect_vulnerability_type(text):
    lowered = text.lower()
    for label, patterns in VULNERABILITY_PATTERNS.items():
        if any(pattern in lowered for pattern in patterns):
            return label
    explicit = re.search(r"(?:açık türü|acik turu|vulnerability type|vuln type|type)\s*[:=]\s*([^\n,;]+)", text, re.I)
    if explicit and len(explicit.group(1).strip()) >= 2:
        return explicit.group(1).strip()[:60]
    return None

def detect_affected_target(text):
    match = URL_RE.search(text)
    if match:
        return match.group(0).strip()
    explicit = re.search(r"(?:url|endpoint|etkilenen)\s*[:=]\s*([^\n\s]+)", text, re.I)
    if explicit:
        return explicit.group(1).strip()
    return None

def has_trigger_details(text):
    lowered = text.lower()
    if any(word in lowered for word in TRIGGER_WORDS):
        return True
    return bool(re.search(r"(^|\n)\s*(1[.)]|2[.)]|3[.)]|-)\s+", text))

def has_impact_details(text):
    lowered = text.lower()
    for word in IMPACT_WORDS:
        if re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", lowered):
            return True
    return False

def analyze_report(text):
    vulnerability_type = detect_vulnerability_type(text)
    affected_target = detect_affected_target(text)
    severity_match = SEVERITY_RE.search(text)
    severity = normalize_severity(severity_match.group(1)) if severity_match else None
    missing = []
    if not vulnerability_type:
        missing.append("Açık türü")
    if not affected_target:
        missing.append("Etkilenen URL veya endpoint")
    if not has_trigger_details(text):
        missing.append("Nasıl tetikleniyor")
    if not has_impact_details(text):
        missing.append("Etki/Risk")
    if not severity:
        missing.append("Severity")
    return {"complete": not missing, "missing": missing, "type": vulnerability_type, "target": affected_target, "severity": severity}

def missing_message(missing):
    return "Raporun eksik bilgileri var: " + ", ".join(missing) + ". Lütfen tamamla."

def fallback_report(text, analysis):
    vuln = analysis.get("type") or "Belirtilen açık"
    severity = analysis.get("severity") or "Belirtilmedi"
    target = analysis.get("target") or "Belirtilmedi"
    return (
        f"Title: {target} üzerinde {vuln}\n\n"
        f"Açıklama: 0xVault incelemesi kapsamında hedefte {vuln} türünde bir güvenlik zafiyeti tespit edildi. Bulgular yetkili bug bounty veya sorumlu açıklama kapsamı içinde değerlendirilmelidir.\n\n"
        f"Severity: {severity}\n\n"
        f"Etkilenen URL/Endpoint: {target}\n\n"
        f"Açık Türü: {vuln}\n\n"
        f"Teknik Detay: {text.strip()}\n\n"
        f"Yeniden Üretim Adımları: Kullanıcının sağladığı tetikleme akışı ve PoC adımları teknik detay bölümünde korunmuştur.\n\n"
        f"Etki/Risk: Bu zafiyet, bildirilen senaryoya göre yetkisiz işlem, veri erişimi veya güvenlik kontrolü atlatma riski doğurabilir.\n\n"
        f"Kanıt/PoC: {text.strip()}\n\n"
        f"Önerilen Çözüm: Girdi doğrulama, yetkilendirme kontrolleri, güvenli varsayılanlar, kapsamlı loglama ve regresyon testleri uygulanmalıdır.\n\n"
        f"Doğrulama Notları: Düzeltme sonrası aynı endpoint üzerinde yetkili ve yetkisiz kullanıcı senaryoları ayrı ayrı test edilmelidir."
    )

def generate_ai(system_prompt, user_prompt, temperature=0.35):
    if not GEMINI_API_KEY:
        raise AiServiceError("AI key eksik")
    base = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    headers = {"Content-Type": "application/json"}
    if GEMINI_AUTH_MODE == "bearer":
        url = base
        headers["Authorization"] = f"Bearer {GEMINI_API_KEY}"
    else:
        url = base + "?" + urllib.parse.urlencode({"key": GEMINI_API_KEY})
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {"temperature": temperature, "topP": 0.9, "maxOutputTokens": 2048},
    }
    status, data = http_json(url, payload, headers=headers, timeout=AI_TIMEOUT_SECONDS)
    raw = json.dumps(data, ensure_ascii=False)[:800]
    if status == 429 or "RESOURCE_EXHAUSTED" in raw or "quota" in raw.lower() or "limit" in raw.lower():
        raise AiLimitError()
    if status >= 400:
        raise AiServiceError(raw)
    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(part.get("text", "") for part in parts).strip()
    except Exception as exc:
        raise AiServiceError(str(exc))
    if not text:
        raise AiServiceError("boş yanıt")
    return text

def is_allowed(message):
    chat = message.get("chat", {})
    return chat.get("id") == ALLOWED_CHAT_ID and chat.get("type") in {"group", "supergroup"}

def command_and_args(text):
    if not text.startswith("/"):
        return "", ""
    first, _, rest = text.partition(" ")
    command = first.split("@", 1)[0].lower()
    return command, rest.strip()

def handle_chat(message, args):
    chat_id = message["chat"]["id"]
    msg_id = message.get("message_id")
    user_id = message.get("from", {}).get("id", 0)
    state = user_state[user_id]
    if state.get(REPORT_MODE):
        send_message(chat_id, "Şu an rapor modundasın. Sohbete dönmek için önce /exitreport veya /cancel yaz.", msg_id)
        return
    allowed, retry = allow_rate(user_id, "chat", CHAT_RATE_LIMIT_COUNT, CHAT_RATE_LIMIT_WINDOW_SECONDS)
    if not allowed:
        send_message(chat_id, f"Rate limit aşıldı. {retry} saniye sonra tekrar dene.", msg_id)
        return
    if not args:
        send_message(chat_id, "Mesajını /chat komutundan sonra yaz. Örnek: /chat IDOR nasıl raporlanır?", msg_id)
        return
    try:
        answer = generate_ai(CYBER_SYSTEM_PROMPT, f"Kullanıcı mesajı:\n{args}", 0.3)
    except AiLimitError:
        answer = LIMIT_MESSAGE
    except Exception as exc:
        logging.warning("AI chat error: %s", exc)
        answer = "AI servisi şu an yanıt veremiyor. Biraz sonra tekrar dene."
    send_message(chat_id, answer, msg_id)

def handle_report_text(message, text):
    chat_id = message["chat"]["id"]
    msg_id = message.get("message_id")
    user_id = message.get("from", {}).get("id", 0)
    allowed, retry = allow_rate(user_id, "report", REPORT_RATE_LIMIT_COUNT, REPORT_RATE_LIMIT_WINDOW_SECONDS)
    if not allowed:
        send_message(chat_id, f"Rapor üretim limiti aşıldı. {retry} saniye sonra tekrar dene.", msg_id)
        return
    state = user_state[user_id]
    previous = state.get(REPORT_DRAFT, "")
    combined = (previous + "\n" + text).strip() if previous else text.strip()
    state[REPORT_DRAFT] = combined
    analysis = analyze_report(combined)
    if not analysis["complete"]:
        send_message(chat_id, missing_message(analysis["missing"]), msg_id)
        return
    prompt = (
        "Aşağıdaki bulguyu bug bounty raporuna dönüştür. Bilgileri uydurma, belirsiz yerlerde kontrollü ifade kullan.\n\n"
        f"Tespit edilen açık türü: {analysis['type']}\n"
        f"Tespit edilen hedef: {analysis['target']}\n"
        f"Tespit edilen severity: {analysis['severity']}\n\n"
        f"Ham bulgu:\n{combined}"
    )
    try:
        report = generate_ai(REPORT_SYSTEM_PROMPT, prompt, 0.2)
    except AiLimitError:
        send_message(chat_id, LIMIT_MESSAGE, msg_id)
        return
    except Exception as exc:
        logging.warning("AI report error: %s", exc)
        report = fallback_report(combined, analysis)
    state.pop(REPORT_MODE, None)
    state.pop(REPORT_DRAFT, None)
    send_message(chat_id, report, msg_id)

def handle_message(message):
    text = (message.get("text") or "").strip()
    if not text:
        return
    chat = message.get("chat", {})
    chat_id = chat.get("id", 0)
    chat_type = chat.get("type", "unknown")
    msg_id = message.get("message_id")
    user_id = message.get("from", {}).get("id", 0)
    logging.info("Incoming message chat_id=%s chat_type=%s user_id=%s text=%s", chat_id, chat_type, user_id, text[:80])
    command, args = command_and_args(text)
    if command == "/id":
        send_message(chat_id, f"Chat ID: {chat_id}\nChat type: {chat_type}\nAllowed chat ID: {ALLOWED_CHAT_ID}", msg_id)
        return
    if not is_allowed(message):
        logging.info("Ignored unauthorized chat_id=%s chat_type=%s allowed_chat_id=%s", chat_id, chat_type, ALLOWED_CHAT_ID)
        return
    state = user_state[user_id]
    if command == "/help":
        send_message(chat_id, HELP_TR, msg_id)
    elif command == "/cancel":
        clear_user(user_id)
        send_message(chat_id, "İptal edildi. Aktif işlem durduruldu.", msg_id)
    elif command == "/report":
        state[REPORT_MODE] = True
        state[REPORT_DRAFT] = ""
        send_message(chat_id, REPORT_INTRO_TR, msg_id)
    elif command == "/exitreport":
        if state.get(REPORT_MODE):
            state.pop(REPORT_MODE, None)
            state.pop(REPORT_DRAFT, None)
            send_message(chat_id, "Rapor modundan çıkıldı.", msg_id)
        else:
            send_message(chat_id, "Aktif rapor modu yok.", msg_id)
    elif command == "/chat":
        handle_chat(message, args)
    elif state.get(REPORT_MODE):
        if text.startswith("/"):
            send_message(chat_id, "Rapor modundasın. Çıkmak için /exitreport, tamamen iptal etmek için /cancel kullan.", msg_id)
        else:
            handle_report_text(message, text)

def poll_loop():
    offset = 0
    while True:
        try:
            telegram("deleteWebhook", {"drop_pending_updates": True}, retries=5)
            break
        except Exception as exc:
            logging.warning("deleteWebhook failed, retrying without crashing: %s", exc)
            time.sleep(10)
    logging.info("0xVault bot started")
    while True:
        try:
            data = telegram("getUpdates", {"offset": offset, "timeout": 50, "allowed_updates": ["message"]})
            for update in data.get("result", []):
                offset = max(offset, update.get("update_id", 0) + 1)
                message = update.get("message")
                if message:
                    handle_message(message)
        except KeyboardInterrupt:
            raise
        except Exception:
            logging.error("poll error\n%s", traceback.format_exc())
            time.sleep(3)

def validate_config():
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
    if missing:
        raise RuntimeError("Eksik secret/env: " + ", ".join(missing))

if __name__ == "__main__":
    validate_config()
    start_health_server()
    poll_loop()
