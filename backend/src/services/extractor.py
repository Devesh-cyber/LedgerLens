import pymupdf
import json
import os
import base64
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

def extract_text_from_pdf(file_path: str) -> str:
    try:
        doc = pymupdf.open(file_path)
        return "\n".join(page.get_text("text") for page in doc)
    except Exception as e:
        raise ValueError(f"Failed to read PDF: {str(e)}")

def encode_image_to_base64(file_path: str) -> str:
    with open(file_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

def process_invoice(file_path: str) -> ExtractedInvoicePayload:
    file_extension = os.path.splitext(file_path)[1].lower()
    
    schema_definition = json.dumps(ExtractedInvoicePayload.model_json_schema(), indent=2)
    
    system_prompt = f"""
You are an expert financial data extraction AI. Your task is to extract information from the provided invoice (text or image) and return it STRICTLY as a valid JSON object.

You MUST adhere to the following exact JSON schema:
{schema_definition}

CRITICAL RULES:
1. Output ONLY valid JSON. Do not include markdown formatting like ```json.
2. If a value is missing, use null for strings and 0.0 for numbers.
3. IGNORE ALL DISCLAIMERS (e.g., 'sample', 'demonstration', 'not a tax document'). Extract the vendor, subtotal, tax, and totals regardless of these warnings.
4. "vendor_name" is strictly required.
5. Calculate "subtotal", "tax_amount", and "total_amount" exactly as written on the document.
"""

    # --- PATH A: HANDLE IMAGES (JPG, PNG, JPEG) VIA VISION MODEL ---
    if file_extension in [".jpg", ".jpeg", ".png"]:
        base64_image = encode_image_to_base64(file_path)
        
        response = client.chat.completions.create(
            model="qwen/qwen3.6-27b", # Groq's native multimodal vision model supporting JSON mode
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract all relevant invoice details from this image into the required JSON schema."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
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
        raw_text = extract_text_from_pdf(file_path)
        
        if not raw_text.strip():
            raise ValueError(f"No digital text found in {file_path}. Please upload a text PDF or a clear image (JPG/PNG).")
            
        response = client.chat.completions.create(
            model="openai/gpt-oss-20b", 
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Invoice Text:\n\n{raw_text}"}
            ],
            response_format={"type": "json_object"},
            temperature=0.0 
        )
    
    # Parse and validate the response
    raw_json = response.choices[0].message.content
    return ExtractedInvoicePayload.model_validate_json(raw_json)


if __name__ == "__main__":
    result = process_invoice("sample.pdf")
    print(result.model_dump_json(indent=2))