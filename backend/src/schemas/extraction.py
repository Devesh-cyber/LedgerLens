from datetime import date
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

class ExtractedLineItem(BaseModel):
    description: str = Field(description="Description of product or service")
    quantity: float = Field(default=1.0)
    unit_price: float = Field(default=0.0)
    line_total: float = Field(default=0.0)

class ExtractedInvoicePayload(BaseModel):
    vendor_name: str
    vendor_tax_id: Optional[str] = Field(default=None)
    invoice_number: Optional[str] = Field(default=None)
    invoice_date: Optional[date] = Field(default=None)
    due_date: Optional[date] = Field(default=None)
    
    subtotal: float
    tax_amount: float
    total_amount: float
    
    spending_category: Optional[str] = Field(default="General Expense")
    line_items: List[ExtractedLineItem] = Field(default=[])
    
    # No default: if the model doesn't return a confidence value, we want to
    # know that explicitly (treated as "unknown" -> routed to review) rather
    # than silently assuming a fixed 0.90 "confidence" that isn't real.
    overall_confidence: Optional[float] = Field(default=None)
    field_confidences: Dict[str, float] = Field(default_factory=dict)

class InvoiceUpdate(BaseModel):
    vendor_name: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    subtotal: Optional[float] = None
    tax_amount: Optional[float] = None
    total_amount: Optional[float] = None