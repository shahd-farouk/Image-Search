import requests
from pathlib import Path
from datetime import datetime
import shutil
from furniture import Util, Furniture, FurnitureRepository

# ---------- Config ----------
UPLOAD_DIR = Path("static/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

BASE_IMAGE_URL = "https://test-eg.homzmart.net/catalog/product"
INDEX = Util.get_index_name()

es = Util.get_connection()
repo = FurnitureRepository(es, INDEX)

# ---------- Fetch products ----------
def fetch_products(from_idx=0, size=100):
    url = f"http://10.55.99.22:9200/{INDEX}/_search?from={from_idx}&size={size}"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    data = response.json()
    return data.get("hits", {}).get("hits", [])

# ---------- Download media ----------
def download_and_prepare_media(media_gallery):
    prepared_gallery = []

    for media in media_gallery:
        file_path = media.get("file")
        if not file_path:
            continue

        dest_filename = Path(file_path).name
        dest_path = UPLOAD_DIR / dest_filename
        file_url = f"{BASE_IMAGE_URL}{file_path}"

        if not dest_path.exists():
            try:
                r = requests.get(file_url, stream=True, timeout=30)
                if r.status_code == 200:
                    with open(dest_path, 'wb') as f:
                        shutil.copyfileobj(r.raw, f)
                else:
                    continue
            except Exception:
                continue

        prepared_gallery.append({
            "id": media.get("id"),
            "media_type": media.get("media_type", "image"),
            "file": str(dest_path),  # absolute/local path for embeddings
            "position": media.get("position", 1),
            "disabled": media.get("disabled", False),
            "types": media.get("types", ["image"])
        })

    return prepared_gallery

# ---------- Import products ----------
def import_products(hits):
    items = []

    for hit in hits:
        source = hit.get("_source", {})
        media_gallery = download_and_prepare_media(source.get("media_gallery", []))
        main_image = media_gallery[0]["file"] if media_gallery else ""

        furniture = Furniture(
            sku=source.get("sku"),
            item_name=source.get("name"),
            material_value=source.get("material_value", "Mixed"),
            item_type=source.get("item_type", ""),
            colors=source.get("colors", []),
            dimensions=source.get("dimensions"),
            price=source.get("price", 0),
            special_price=source.get("special_price"),
            final_price=source.get("final_price", 0),
            image_path=main_image,
            description=source.get("description"),
            media_gallery=media_gallery
        )

        items.append(furniture)

    repo.bulk_insert(items, refresh=True)
    print(f"Imported {len(items)} products with embeddings.")

# ---------- Main ----------
if __name__ == "__main__":
    hits = fetch_products(from_idx=0, size=100)
    import_products(hits)