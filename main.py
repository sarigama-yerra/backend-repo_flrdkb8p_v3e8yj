import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from supabase import create_client, Client

# -----------------------------
# Supabase Setup
# -----------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")  # Simple admin gate for dashboard actions

supabase: Optional[Client] = None
if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    except Exception as e:
        supabase = None

# -----------------------------
# FastAPI App
# -----------------------------
app = FastAPI(title="Laptop Catalog API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# Models
# -----------------------------
class LaptopSpec(BaseModel):
    cpu: Optional[str] = None
    gpu: Optional[str] = None
    ram_gb: Optional[int] = Field(default=None, ge=1)
    storage_gb: Optional[int] = Field(default=None, ge=1)
    storage_type: Optional[str] = Field(default=None, description="HDD/SSD/NVMe")
    screen_size_inch: Optional[float] = Field(default=None, ge=10)
    resolution: Optional[str] = None
    refresh_rate_hz: Optional[int] = Field(default=None, ge=30)
    battery_wh: Optional[float] = Field(default=None, ge=1)
    weight_kg: Optional[float] = Field(default=None, ge=0.5)
    os: Optional[str] = None
    ports: Optional[List[str]] = None

class ProductBase(BaseModel):
    brand: str
    model: str
    title: Optional[str] = None
    description: Optional[str] = None
    price: float = Field(ge=0)
    sale_price: Optional[float] = Field(default=None, ge=0)
    stock: int = Field(ge=0, default=0)
    image_url: Optional[str] = None
    colors: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    specs: Optional[LaptopSpec] = None
    published: bool = True

class ProductCreate(ProductBase):
    pass

class ProductUpdate(BaseModel):
    brand: Optional[str] = None
    model: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = Field(default=None, ge=0)
    sale_price: Optional[float] = Field(default=None, ge=0)
    stock: Optional[int] = Field(default=None, ge=0)
    image_url: Optional[str] = None
    colors: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    specs: Optional[LaptopSpec] = None
    published: Optional[bool] = None

class ProductOut(ProductBase):
    id: int

# -----------------------------
# Utilities
# -----------------------------

def require_admin(x_admin_token: Optional[str] = Header(default=None)):
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=500, detail="ADMIN_TOKEN not set on server")
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized: invalid admin token")


def ensure_supabase():
    if not (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY):
        raise HTTPException(status_code=500, detail="Supabase env not configured (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)")
    if supabase is None:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")
    return supabase

# -----------------------------
# Health
# -----------------------------
@app.get("/")
def read_root():
    return {"message": "Laptop Catalog Backend is running"}

@app.get("/test")
def test_database():
    info = {
        "backend": "✅ Running",
        "supabase_url": "✅ Set" if SUPABASE_URL else "❌ Not Set",
        "service_key": "✅ Set" if SUPABASE_SERVICE_ROLE_KEY else "❌ Not Set",
        "admin_token": "✅ Set" if ADMIN_TOKEN else "⚠️ Not Set",
        "supabase": "✅ Connected" if supabase else "❌ Not Connected",
        "tables": []
    }
    if supabase:
        try:
            # attempt simple query
            _ = supabase.table("products").select("id").limit(1).execute()
            info["tables"].append("products")
        except Exception as e:
            info["supabase"] = f"⚠️ Error querying: {str(e)[:120]}"
    return info

# -----------------------------
# Public Product Endpoints
# -----------------------------
@app.get("/api/products", response_model=List[ProductOut])
def list_products(q: Optional[str] = None, brand: Optional[str] = None, tag: Optional[str] = None):
    sb = ensure_supabase()
    query = sb.table("products").select("*").eq("published", True)
    if brand:
        query = query.ilike("brand", f"%{brand}%")
    if tag:
        query = query.contains("tags", [tag])
    if q:
        # search against multiple fields
        # Supabase doesn't support OR across ilike in python client easily; do title/desc filter in two steps
        query = query.or_(
            f"title.ilike.%{q}%,description.ilike.%{q}%,model.ilike.%{q}%,brand.ilike.%{q}%"
        )
    res = query.order("id", desc=True).execute()
    return res.data or []

@app.get("/api/products/{product_id}", response_model=ProductOut)
def get_product(product_id: int):
    sb = ensure_supabase()
    res = sb.table("products").select("*").eq("id", product_id).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Product not found")
    return res.data

# -----------------------------
# Admin CRUD Endpoints
# -----------------------------
@app.post("/api/admin/products", response_model=ProductOut, dependencies=[Depends(require_admin)])
def create_product(payload: ProductCreate):
    sb = ensure_supabase()
    data = payload.dict()
    res = sb.table("products").insert(data).select("*").single().execute()
    return res.data

@app.put("/api/admin/products/{product_id}", response_model=ProductOut, dependencies=[Depends(require_admin)])
def update_product(product_id: int, payload: ProductUpdate):
    sb = ensure_supabase()
    updates = {k: v for k, v in payload.dict().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    res = sb.table("products").update(updates).eq("id", product_id).select("*").single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Product not found")
    return res.data

@app.delete("/api/admin/products/{product_id}", dependencies=[Depends(require_admin)])
def delete_product(product_id: int):
    sb = ensure_supabase()
    res = sb.table("products").delete().eq("id", product_id).execute()
    if res.count == 0 and not res.data:
        # best effort signal
        raise HTTPException(status_code=404, detail="Product not found or already deleted")
    return {"success": True}

# List all products including unpublished for admin table
@app.get("/api/admin/products", response_model=List[ProductOut], dependencies=[Depends(require_admin)])
def admin_list_products():
    sb = ensure_supabase()
    res = sb.table("products").select("*").order("id", desc=True).execute()
    return res.data or []


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
