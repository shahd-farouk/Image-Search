# app.py
import os
import io
import json
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
import uvicorn
from PIL import Image

from furniture import Util, FurnitureRepository, Furniture

app = FastAPI(title="Furniture Search API")

# connect to ES
es = Util.get_connection()
INDEX = Util.get_index_name()
repo = FurnitureRepository(es, INDEX)

# helper to convert UploadFile to PIL image and a temp path (we can also keep in-memory)
def pil_image_from_upload(upload: UploadFile) -> Image.Image:
    contents = upload.file.read()
    upload.file.seek(0)
    image = Image.open(io.BytesIO(contents)).convert("RGB")
    return image

@app.post("/items/", response_model=dict)
async def add_item(
    item_name: str = Form(...),
    material: str = Form("unknown"),
    item_type: str = Form(""),
    width: Optional[float] = Form(None),
    height: Optional[float] = Form(None),
    colors: str = Form("unknown"),
    description: str = Form(""),
    image: UploadFile = File(...)
):
    # Save the uploaded image temporarily to generate embeddings with SentenceTransformer
    try:
        contents = await image.read()
        pil_img = Image.open(io.BytesIO(contents)).convert("RGB")
    except Exception as e:
        raise HTTPException(400, f"Invalid image: {e}")

    # Save a temp file (or store elsewhere). We'll write to tmp file, because encode_image_from_path expects a path.
    tmp_dir = os.environ.get("TMP_DIR", "/tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_path = os.path.join(tmp_dir, image.filename)
    pil_img.save(tmp_path)

    f = Furniture(
        item_name=item_name,
        material=material,
        item_type=item_type,
        width=width,
        height=height,
        colors=[c.strip() for c in colors.split(",")],
        image_path=tmp_path,
        description=description
    )
    f.generate_embeddings()
    repo.insert(f)
    return {"status": "ok", "item_name": item_name}

@app.post("/search/image")
async def search_by_image(image: UploadFile = File(...), k: int = 5):
    try:
        contents = await image.read()
        pil_img = Image.open(io.BytesIO(contents)).convert("RGB")
    except Exception as e:
        raise HTTPException(400, f"Invalid image: {e}")

    # encode using Furniture.model directly (we have access to model)
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
