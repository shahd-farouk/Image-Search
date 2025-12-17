import os
import io
import uvicorn
from typing import List
from PIL import Image
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from furniture import Util, FurnitureRepository, Furniture

app = FastAPI(title="Furniture Search API")

STATIC_DIR = "static"
UPLOAD_DIR = os.path.join(STATIC_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

es = Util.get_connection()
INDEX = Util.get_index_name()
repo = FurnitureRepository(es, INDEX)

async def save_upload_image(upload: UploadFile) -> str:
    contents = await upload.read()  # use async read
    try:
        img = Image.open(io.BytesIO(contents)).convert("RGB")
    except Exception as e:
        raise HTTPException(400, f"Invalid image: {e}")

    safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in upload.filename)
    rel_path = f"uploads/{safe_name}"           # ← relative path
    abs_path = os.path.join(UPLOAD_DIR, safe_name)

    img.save(abs_path)
    print(f"Saved image: {abs_path}")

    return rel_path

def get_dynamic_terms(fields=["colors", "item_type"]):
    aggs = {f"{f}_agg": {"terms": {"field": f, "size": 1000}} for f in fields}
    resp = es.search(
        index=INDEX,
        size=0,
        body={"aggs": aggs}
    )
    
    results = {}
    for f in fields:
        buckets = resp["aggregations"].get(f"{f}_agg", {}).get("buckets", [])
        results[f] = [b["key"].lower() for b in buckets]
    return results

@app.get("/")
async def serve_ui():
    return FileResponse("static/index.html")


@app.post("/items")
async def add_item(
    sku: str = Form(...),
    item_name: str = Form(...),
    material_value: str = Form("Mixed"),
    item_type: str = Form(""),
    colors: str = Form(""),
    dimensions: str = Form(""),
    price: float = Form(0),
    special_price: float | None = Form(None),
    final_price: float = Form(0),
    description: str = Form(""),
    image: UploadFile = File(...),
):
    image_path = save_upload_image(image)

    furniture = Furniture(
        sku=sku,
        item_name=item_name,
        material_value=material_value,
        item_type=item_type,
        colors=[c.strip() for c in colors.split(",") if c.strip()],
        dimensions=dimensions,
        price=price,
        special_price=special_price,
        final_price=final_price,
        image_path=image_path,
        description=description,
        media_gallery=[{"file": image_path, "media_type": "image"}],
    )

    repo.insert(furniture)

    return {
        "status": "ok",
        "sku": sku,
        "item_name": item_name,
        "image_path": image_path,
    }


@app.get("/search/text")
async def search_by_text(q: str, k: int = 5):
    if not q:
        raise HTTPException(400, "Missing query parameter 'q'")

    dynamic_terms = get_dynamic_terms(fields=["colors", "item_type"])
    colors_list = dynamic_terms.get("colors", [])
    item_types = dynamic_terms.get("item_type", [])

    tokens = q.lower().split()
    color_tokens = [t for t in tokens if t in colors_list]
    type_tokens = [t for t in tokens if t in item_types]
    other_tokens = [t for t in tokens if t not in color_tokens + type_tokens]

    should_clauses = []

    if color_tokens and type_tokens:
        should_clauses.append({
            "bool": {
                "must": [
                    {"terms": {"item_type": type_tokens}},
                    {"terms": {"colors": color_tokens}}
                ],
                "boost": 10.0
            }
        })

    if type_tokens:
        should_clauses.append({
            "terms": {
                "item_type": type_tokens,
                "boost": 6.0
            }
        })

    if other_tokens or tokens:
        should_clauses.append({
            "multi_match": {
                "query": q,
                "fields": [
                    "item_name^1",
                    "description^0.5",
                    "material_value^0.3",
                    "dimensions^0.2",
                    "sku^0.1"
                ],
                "fuzziness": "AUTO",
                "prefix_length": 2,
                "boost": 3.0
            }
        })

    if color_tokens:
        should_clauses.append({
            "terms": {
                "colors": color_tokens,
                "boost": 1.0
            }
        })

    query_body = {
        "size": k,
        "query": {
            "bool": {
                "should": should_clauses,
                "minimum_should_match": 1
            }
        }
    }

    resp = es.search(index=INDEX, body=query_body)
    hits = resp.get("hits", {}).get("hits", [])

    return {
        "results": [
            {**h["_source"], "_score": h["_score"]}
            for h in hits
        ]
    }

@app.get("/suggest")
async def suggest_text(q: str):
    if not q:
        return {"did_you_mean": None}

    suggest_body = {
        "suggest": {
            "spelling": {
                "text": q,
                "term": {
                    "field": "item_name",
                    "suggest_mode": "always"
                }
            }
        }
    }

    try:
        resp = es.suggest(index=INDEX, body=suggest_body)
        options = resp.get("spelling", [])[0].get("options", [])
        return {"did_you_mean": options[0]["text"] if options else None}
    except Exception:
        return {"did_you_mean": None}


@app.post("/search/image")
async def search_by_image(image: UploadFile = File(...), k: int = 5):
    try:
        contents = await image.read()
        img = Image.open(io.BytesIO(contents)).convert("RGB")
    except Exception as e:
        raise HTTPException(400, f"Invalid image: {e}")

    vector = Furniture.model.encode(img).astype(float).tolist()
    resp = repo.search_by_knn("image_embedding", vector, k=k)

    hits = resp.get("hits", {}).get("hits", [])
    return {"results": [h.get("_source", {}) for h in hits]}


@app.post("/search/embedding")
async def search_by_embedding(
    embedding: List[float],
    field: str = "image_embedding",
    k: int = 5
):
    if field not in ("image_embedding", "text_embedding"):
        raise HTTPException(400, "Invalid embedding field")

    resp = repo.search_by_knn(field, embedding, k=k)
    hits = resp.get("hits", {}).get("hits", [])
    return {"results": [h.get("_source", {}) for h in hits]}


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)