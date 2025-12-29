import os
import io
import json
import time
import logging
import uvicorn
from PIL import Image
from typing import List
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from furniture import Util, FurnitureRepository, Furniture
from fastapi import FastAPI, UploadFile, File, Form, HTTPException

app = FastAPI(title="Furniture Search API")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    image_path = await save_upload_image(image)

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

# Simple in-memory cache for dynamic terms
DYNAMIC_TERMS_CACHE = {"colors": [], "item_type": []}
DYNAMIC_TERMS_LAST_FETCH = 0
CACHE_TTL_SECONDS = 300  # refresh every 5 minutes

@app.get("/search/text")
async def search_by_text(q: str, k: int = 5):
    if not q:
        raise HTTPException(400, "Missing query parameter 'q'")

    global DYNAMIC_TERMS_CACHE, DYNAMIC_TERMS_LAST_FETCH
    now = time.time()
    if now - DYNAMIC_TERMS_LAST_FETCH > CACHE_TTL_SECONDS or not DYNAMIC_TERMS_CACHE["colors"]:
        DYNAMIC_TERMS_CACHE = get_dynamic_terms(fields=["colors", "item_type"])
        DYNAMIC_TERMS_LAST_FETCH = now
        logger.info(f"Dynamic terms cache refreshed: {DYNAMIC_TERMS_CACHE}")

    colors_list = [c.lower() for c in DYNAMIC_TERMS_CACHE.get("colors", [])]
    item_types_list = [t.lower() for t in DYNAMIC_TERMS_CACHE.get("item_type", [])]

    logger.info(f"Colors list (lowercased): {colors_list}")
    logger.info(f"Item types list (lowercased): {item_types_list}")

    tokens = q.split()
    tokens_lower = [t.lower() for t in tokens]

    logger.info(f"Query tokens: {tokens}")
    logger.info(f"Query tokens lowercased: {tokens_lower}")

    color_tokens = [t for t in tokens_lower if t in colors_list]
    type_tokens = [t for t in tokens_lower if t in item_types_list]
    other_tokens = [t for t in tokens_lower if t not in color_tokens + type_tokens]

    logger.info(f"Identified color tokens: {color_tokens}")
    logger.info(f"Identified item_type tokens: {type_tokens}")
    logger.info(f"Other tokens: {other_tokens}")

    should_clauses = []

    if type_tokens:
        should_clauses.append({
            "terms": {
                "item_type.keyword": type_tokens,
                "boost": 10.0
            }
        })
        logger.info(f"Added item_type terms clause: {type_tokens}")

    if color_tokens:
        should_clauses.append({
            "terms": {
                "colors.keyword": color_tokens,
                "boost": 6.0
            }
        })
        logger.info(f"Added colors terms clause: {color_tokens}")

    if other_tokens or tokens:
        should_clauses.append({
            "multi_match": {
                "query": q,
                "fields": [
                    "item_name^2",
                    "description^1",
                    "material_value^0.5",
                    "dimensions^0.3",
                    "sku^0.1"
                ],
                "fuzziness": "AUTO",
                "prefix_length": 2,
                "boost": 3.0
            }
        })
        logger.info("Added fuzzy multi_match clause for free-text search")

    query_body = {
        "size": k,
        "query": {
            "bool": {
                "should": should_clauses,
                "minimum_should_match": 1
            }
        }
    }

    # Pretty-print the query
    logger.info("Final Elasticsearch query:\n%s", json.dumps(query_body, indent=4))

    resp = es.search(index=INDEX, body=query_body)
    hits = resp.get("hits", {}).get("hits", [])

    logger.info(f"Number of hits: {len(hits)}")

    return {
        "results": [
            {**h["_source"], "_score": h["_score"]}
            for h in hits
        ]
    }

@app.get("/suggest")
async def suggest_text(q: str):
    if not q:
        logger.info("null ml awl")
        return {"did_you_mean": None}

    suggest_body = {
        "suggest": {
            "autocomplete": {
                "prefix": q,
                "completion": {
                    "field": "item_name_suggest",
                    "skip_duplicates": True,
                    "size": 1
                }
            }
        }
    }

    try:
        resp = es.search(index=INDEX, body=suggest_body, request_timeout=10)

        options = (
            resp
            .get("suggest", {})
            .get("autocomplete", [])[0]
            .get("options", [])
        )

        if options:
            logger.info("no options avaliable")
            return {"did_you_mean": options[0]["text"]}

        logger.info("mfesh haga returned aslan")
        return {"did_you_mean": None}

    except Exception as e:
        logger.exception(e)
        logger.info("exception hasal")
        return {"did_you_mean": None}

MIN_SIMILARITY = 0.7
CANDIDATE_K = 50

@app.post("/search/image")
async def search_by_image(image: UploadFile = File(...), k: int = 5):
    try:
        contents = await image.read()
        img = Image.open(io.BytesIO(contents)).convert("RGB")
    except Exception as e:
        raise HTTPException(400, f"Invalid image: {e}")

    # IMPORTANT: normalize embeddings
    vector = (
        Furniture.model.encode(img, normalize_embeddings=True)
        .astype(float)
        .tolist()
    )

    # Step 1: retrieve candidates
    resp = repo.search_by_knn(
        field="image_embedding",
        vector=vector,
        k=CANDIDATE_K
    )

    hits = resp.get("hits", {}).get("hits", [])

    # Step 2: filter by similarity threshold
    filtered_hits = [
        h for h in hits
        if h.get("_score", 0) >= MIN_SIMILARITY
    ]

    # Step 3: sort by score (descending)
    filtered_hits.sort(key=lambda h: h["_score"], reverse=True)

    # Step 4: limit to requested k
    final_hits = filtered_hits[:k]

    # Optional: reject low-confidence searches entirely
    if not final_hits:
        return {
            "results": [],
            "message": "No confident image matches found"
        }

    return {
        "results": [
            {
                **h["_source"],
                "_score": h["_score"]
            }
            for h in final_hits
        ]
    }

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