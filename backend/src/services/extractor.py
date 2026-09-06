import pymupdf
import json
import os
import base64
import requests
from dotenv import load_dotenv
from openai import OpenAI
from src.schemas.extraction import ExtractedInvoicePayload

# 1. Force Python to read the .env file
load_dotenv()

# 2. Verify the key exists before connecting
api_key = os.environ.get("GROQ_API_KEY")
if not api_key:
    raise ValueError("CRITICAL: GROQ_API_KEY is missing. Ensure your .env file exists in the root folder.")

client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=api_key
)

def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    try:
        # PyMuPDF natively supports reading directly from memory buffers
        doc = pymupdf.open("pdf", pdf_bytes)
        return "\n".join(page.get_text("text") for page in doc)
    except Exception as e:
        raise ValueError(f"Failed to read PDF stream: {str(e)}")

def encode_image_bytes_to_base64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")

def process_invoice(file_url: str) -> ExtractedInvoicePayload:
    # 1. Fetch file from Supabase URL into memory
    try:
        response = requests.get(file_url, timeout=30)
        response.raise_for_status()
        file_bytes = response.content
    except Exception as e:
        raise ValueError(f"Failed to download file from {file_url}: {str(e)}")

    # Clean the URL to extract the true file extension (ignoring query parameters)
    clean_url = file_url.split("?")[0]
    file_extension = os.path.splitext(clean_url)[1].lower()
    
    schema_definition = json.dumps(ExtractedInvoicePayload.model_json_schema(), indent=2)
    
    system_prompt = f"""
You are an expert financial data extraction AI. Your task is to extract information from the provided invoice (text or image) and return it STRICTLY as a valid JSON object.

You MUST adhere to the following exact JSON schema:
{schema_definition}

CRITICAL RULES:
1. Output ONLY valid JSON. Do not include markdown formatting like ```json.
2. If a value is genuinely missing or cannot be determined reliably, use null. Do not use 0.0 to represent an unknown value. Use 0.0 only when the invoice explicitly indicates that the value is zero.
3. IGNORE ALL DISCLAIMERS (e.g., 'sample', 'demonstration', 'not a tax document'). Extract the vendor, subtotal, tax, and totals regardless of these warnings.
4. "vendor_name" is strictly required.
5. "invoice_number" must be extracted whenever the document contains a field explicitly labeled "Invoice Number", "Invoice No", "Invoice #", or an equivalent label. Do not leave invoice_number null when such a labeled value is clearly present.
6. Calculate "subtotal", "tax_amount", and "total_amount" exactly as written on the document.
7. Do not confuse invoice_number with booking ID, transaction ID, payment reference, customer ID, GSTIN, or other reference numbers. Prefer the value directly associated with the invoice-number label.
8. If multiple reference numbers appear, use the one explicitly identified as the invoice number.
"""

    # --- PATH A: HANDLE IMAGES (JPG, PNG, JPEG) VIA VISION MODEL ---
    if file_extension in [".jpg", ".jpeg", ".png"]:
        base64_image = encode_image_bytes_to_base64(file_bytes)

        # Use the correct MIME type for the actual file extension instead of
        # hardcoding image/jpeg (was previously mislabeling PNGs, which some
        # vision models reject or misread).
        image_mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
        image_mime_type = image_mime_map[file_extension]

        response = client.chat.completions.create(
            model="qwen/qwen3.6-27b",
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract all relevant invoice details from this image into the required JSON schema."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{image_mime_type};base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        
    # --- PATH B: HANDLE PDFs VIA TEXT EXTRACTION ---
    else:
        raw_text = extract_text_from_pdf_bytes(file_bytes)
        
        if not raw_text.strip():
            raise ValueError("No digital text found. Please upload a text PDF or a clear image (JPG/PNG).")
            
        response = client.chat.completions.create(
            model="openai/gpt-oss-20b", 
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Invoice Text:\n\n{raw_text}"}
            ],
            response_format={"type": "json_object"},
            temperature=0.0 
        )
    
    raw_json = response.choices[0].message.content
    return ExtractedInvoicePayload.model_validate_json(raw_json)