"""Turns an uploaded document (image / PDF / text) into (doc_type, text). Images are read with an OpenAI vision model."""
import asyncio, base64, io, os, re
from openai import AsyncOpenAI

ALLOWED = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
           ".pdf": "application/pdf", ".txt": "text/plain"}
MAX_BYTES = 5 * 1024 * 1024
LABELS = {"PAN": "PAN card", "AADHAAR": "Aadhaar", "SALARY_SLIP": "Salary slip / ITR",
          "PROPERTY_DOC": "Property document", "VEHICLE_QUOTATION": "Vehicle quotation",
          "BUSINESS_PROOF": "Business proof (GST / Udyam)"}
KEYWORDS = {
    "PAN": ["permanent account number", "income tax department", "pan card"],
    "AADHAAR": ["aadhaar", "aadhar", "uidai", "unique identification", "xxxx xxxx"],
    "SALARY_SLIP": ["salary slip", "payslip", "pay slip", "net pay", "net salary", "gross salary", "form 16",
                    "income tax return", "itr", "assessment year", "bank statement", "account statement"],
    "PROPERTY_DOC": ["sale deed", "agreement to sell", "sale agreement", "title deed", "property", "survey no",
                     "sub-registrar", "encumbrance", "flat no", "plot no"],
    "VEHICLE_QUOTATION": ["quotation", "proforma", "ex-showroom", "on-road", "chassis", "vehicle", "showroom",
                          "registration certificate"],
    "BUSINESS_PROOF": ["gstin", "gst registration", "udyam", "msme", "shop and establishment",
                       "certificate of incorporation", "partnership deed", "trade licence", "trade license"],
}

def mask_sensitive(text: str) -> str:
    """Keep only the last 4 digits of any 12-digit (Aadhaar-like) number before it is stored."""
    return re.sub(r"\b\d{4}[ -]?\d{4}[ -]?(\d{4})\b", r"XXXX XXXX \1", text)

def classify(text: str) -> str | None:
    """Keyword guess of the document type. Returns None when nothing matches or two types tie."""
    low = text.lower()
    scores = {t: sum(bool(re.search(r"\b" + re.escape(k) + r"\b", low)) for k in ks) for t, ks in KEYWORDS.items()}
    if re.search(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", text):
        scores["PAN"] += 1
    best = max(scores.values())
    top = [t for t, s in scores.items() if s == best]
    return top[0] if best > 0 and len(top) == 1 else None

def _model() -> str:
    return os.getenv("OPENAI_VISION_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

async def _vision(data: bytes, mime: str) -> tuple[str | None, str]:
    b64 = base64.b64encode(data).decode()
    prompt = ("Look at this document. Line 1 must be 'DOC_TYPE: ' followed by exactly one of PAN, AADHAAR, SALARY_SLIP, "
              "PROPERTY_DOC, VEHICLE_QUOTATION, BUSINESS_PROOF, OTHER. (SALARY_SLIP = salary slip, payslip, Form 16, ITR or bank "
              "statement used as income proof. PROPERTY_DOC = sale deed, agreement to sell or other property papers. "
              "VEHICLE_QUOTATION = dealer quotation or proforma invoice for a vehicle. BUSINESS_PROOF = GST certificate, "
              "Udyam/MSME, shop licence or incorporation certificate.) Then transcribe all printed text exactly, one line per "
              "field. Output only that.")
    r = await AsyncOpenAI().chat.completions.create(
        model=_model(), max_tokens=1000,
        messages=[{"role": "user", "content": [{"type": "text", "text": prompt},
                                               {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}]}])
    out = r.choices[0].message.content or ""
    m = re.match(r"\s*DOC_TYPE:\s*([A-Z_]+)[ \t]*\n?(.*)", out, re.S)
    if m:
        return (m.group(1) if m.group(1) in LABELS else None), m.group(2).strip()
    return None, out.strip()

async def _llm_classify(text: str) -> str | None:
    """Fallback when the keywords are not enough."""
    try:
        r = await AsyncOpenAI().chat.completions.create(
            model=_model(), max_tokens=8,
            messages=[{"role": "user", "content": "Classify this Indian loan document. Answer with exactly one of: "
                       "PAN, AADHAAR, SALARY_SLIP, PROPERTY_DOC, VEHICLE_QUOTATION, BUSINESS_PROOF, OTHER.\n\n" + text[:2500]}])
        ans = (r.choices[0].message.content or "").strip().upper()
        return ans if ans in LABELS else None
    except Exception:  # noqa: BLE001
        return None

def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages[:5])

async def extract(data: bytes, filename: str) -> tuple[str | None, str]:
    """Return (doc_type or None, text). doc_type None means the type could not be worked out."""
    ext = os.path.splitext(filename or "")[1].lower()
    dtype: str | None = None
    if ext == ".pdf":
        text = await asyncio.to_thread(_pdf_text, data)
    elif ext == ".txt":
        text = data.decode("utf-8", "ignore")
    else:
        dtype, text = await _vision(data, ALLOWED.get(ext, "image/jpeg"))
    text = text.strip()[:4000]
    if dtype is None and len(text) >= 15:
        dtype = classify(text) or await _llm_classify(text)
    return dtype, text
