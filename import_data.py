import time
import shutil
import requests
from pathlib import Path
from furniture import Util, Furniture, FurnitureRepository, Furniture

# ---------- Config ----------
UPLOAD_DIR = Path("static/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MY_BASE_URL = "https://api.homzmart.com"
PRODUCT_SEARCH_ENDPOINT = f"{MY_BASE_URL}/search/web/v3/search/group/product"

INDEX = Util.get_index_name()

# ---------- Elasticsearch setup ----------
es = Util.get_connection()
# Delete and recreate the index on each run
repo = FurnitureRepository(es, INDEX, force=True)

# ---------- Fetch products ----------
def fetch_products(page=2, page_size=100):
    headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "PostmanRuntime/7.31.3",
            "Origin": MY_BASE_URL,
            "Referer": MY_BASE_URL + "/"
        }

    payload = {
            "currentPage": page,
            "pageSize": page_size,
            "sort": "default",
            "lang": "en"
        }

    session = requests.Session()
    session.headers.update(headers)

    response = session.post(PRODUCT_SEARCH_ENDPOINT, json=payload, timeout=30)
    response.raise_for_status()
    data = response.json()

    items = data.get("data", {}).get("products", {}).get("items", [])
    print(f"Fetched page {page}, items: {len(items)}")
    return items

# ---------- Download media ----------
def download_and_prepare_media(product, retries=2, backoff=2):
    prepared_gallery = []

    # Collect all image URLs: main + gallery
    image_urls = []

    # main image
    main_image_url = product.get("image", {}).get("url")
    if main_image_url:
        image_urls = [main_image_url]
    else:
        image_urls = []

    # gallery images
    gallery_images = product.get("media_gallery", [])[:0]
    for img in gallery_images:
        url = img.get("url")
        if url:
            image_urls.append(url)

    # download all images
    for position, image_url in enumerate(image_urls, start=1):
        dest_filename = Path(image_url).name.split("?")[0]
        dest_path = UPLOAD_DIR / dest_filename

        if not dest_path.exists():
            attempt = 0
            while attempt <= retries:
                try:
                    r = requests.get(image_url, stream=True, timeout=30)
                    r.raise_for_status()
                    with open(dest_path, "wb") as f:
                        shutil.copyfileobj(r.raw, f)
                    print(f"Downloaded: {dest_path}")
                    break
                except Exception as e:
                    attempt += 1
                    if attempt > retries:
                        print(f"Failed to download {image_url} after {retries} retries: {e}")
                        dest_path = None
                    else:
                        print(f"Retrying download ({attempt}/{retries}) for {image_url} in {backoff}s...")
                        time.sleep(backoff)

        # add to gallery only if downloaded successfully
        if dest_path and dest_path.exists():
            prepared_gallery.append({
                "id": product.get("id"),
                "media_type": "image",
                "file": f"uploads/{dest_filename}",
                "position": position,
                "disabled": False,
                "types": ["image"]
            })

    return prepared_gallery

# ---------- Import products ----------
def import_products(products):
    items = []

    products_with_images = 0

    for product in products:
        media_gallery = download_and_prepare_media(product)
        if media_gallery:
            products_with_images += 1

        image_path = media_gallery[0]["file"] if media_gallery else ""

        description = product.get("description")
        if not isinstance(description, str):
            description = ""

        furniture = Furniture(
            sku=product.get("sku") or product.get("id"),
            item_name=product.get("name"),
            material_value=product.get("material", "Mixed"),
            item_type=product.get("type_id", ""),
            colors=product.get("colors", []),
            dimensions=product.get("dimensions"),
            price=product.get("price", 0),
            special_price=product.get("special_price"),
            final_price=product.get("final_price", product.get("price", 0)),
            image_path=image_path,
            description=description,
            media_gallery=media_gallery
        )

        items.append(furniture)

    repo.bulk_insert(items, refresh=True)
    print(f"Total products fetched: {len(products)}")
    print(f"Products with images: {products_with_images}")
    print(f"Imported {len(items)} products with embeddings.")

# ---------- Main ----------
if __name__ == "__main__":
    INDEX = Util.get_index_name()
    es = Util.get_connection()

    if es.indices.exists(index=INDEX):
        print(f"Deleting existing index: {INDEX}")
        es.indices.delete(index=INDEX)

    print(f"Creating index: {INDEX}")
    repo = FurnitureRepository(es, INDEX, force=True)

    # ---------- Fetch and import ----------
    products = fetch_products()
    import_products(products)