# app.py
import os
import io
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
import uvicorn
from PIL import Image

from furniture import Util, FurnitureRepository, Furniture
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI(title="Furniture Search API")

# Serve static files including uploaded images
STATIC_DIR = "static"
UPLOAD_DIR = os.path.join(STATIC_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Connect to Elasticsearch
es = Util.get_connection()
INDEX = Util.get_index_name()
repo = FurnitureRepository(es, INDEX)


# Helper: convert UploadFile to PIL Image
def pil_image_from_upload(upload: UploadFile) -> Image.Image:
    contents = upload.file.read()
    upload.file.seek(0)
    image = Image.open(io.BytesIO(contents)).convert("RGB")
    return image

@app.get("/")
async def serve_ui():
    return FileResponse("static/index.html")

@app.post("/items/", response_model=dict)
async def add_item(
    item_name: str = Form(...),
    material: str = Form("unknown"),
    item_type: str = Form(""),
    width: Optional[float] = Form(None),
    height: Optional[float] = Form(None),
    colors: str = Form("unknown"),
    description: str = Form(""),
    image: UploadFile = File(...),
):
    # Convert uploaded image to PIL
    try:
        contents = await image.read()
        pil_img = Image.open(io.BytesIO(contents)).convert("RGB")
    except Exception as e:
        raise HTTPException(400, f"Invalid image: {e}")

    # Save image under /static/uploads
    safe_filename = image.filename.replace(" ", "_")
    save_path = os.path.join(UPLOAD_DIR, safe_filename)
    pil_img.save(save_path)
    relative_path = f"/static/uploads/{safe_filename}"

    # Create Furniture object
    f = Furniture(
        item_name=item_name,
        material=material,
        item_type=item_type,
        width=width,
        height=height,
        colors=[c.strip() for c in colors.split(",")],
        image_path=relative_path,  # use serveable path
        description=description
    )
    f.generate_embeddings()
    repo.insert(f)
    return {"status": "ok", "item_name": item_name, "image_path": relative_path}


@app.post("/search/image")
async def search_by_image(image: UploadFile = File(...), k: int = 5):
    if not image:
        raise HTTPException(400, "No image uploaded")

    try:
        contents = await image.read()
        pil_img = Image.open(io.BytesIO(contents)).convert("RGB")
    except Exception as e:
        raise HTTPException(400, f"Invalid image: {e}")

    # Generate embedding
    emb = Furniture.model.encode(pil_img).astype(float).tolist()
    resp = repo.search_by_knn("image_embedding", emb, k=k)
    hits = resp.get("hits", {}).get("hits", [])
    results = [h.get("_source", {}) for h in hits]

    return JSONResponse({"results": results})


@app.get("/search/text")
async def search_by_text(q: str, k: int = 5):
    if not q:
        raise HTTPException(400, "Missing query parameter 'q'")

    emb = Furniture.model.encode(q).astype(float).tolist()
    resp = repo.search_by_knn("text_embedding", emb, k=k)
    hits = resp.get("hits", {}).get("hits", [])
    results = [h.get("_source", {}) for h in hits]

    return JSONResponse({"results": results})


@app.post("/search/embedding")
async def search_by_embedding(embedding: List[float], field: str = "image_embedding", k: int = 5):
    if field not in ("image_embedding", "text_embedding"):
        raise HTTPException(400, "field must be 'image_embedding' or 'text_embedding'")

    resp = repo.search_by_knn(field, embedding, k=k)
    hits = resp.get("hits", {}).get("hits", [])
    results = [h.get("_source", {}) for h in hits]

    return JSONResponse({"results": results})


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)