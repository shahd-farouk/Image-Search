import os
import time
import shutil
import requests
from pathlib import Path
from dotenv import load_dotenv
from furniture import Util, Furniture, FurnitureRepository

# ---------- Config ----------
UPLOAD_DIR = Path("static/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv()
MY_BASE_URL = os.getenv("BASE_URL")

if not MY_BASE_URL:
    raise ValueError("BASE_URL is not set in the .env file")

PRODUCT_SEARCH_ENDPOINT = f"{MY_BASE_URL}/search/web/v3/search/group/product"

INDEX = Util.get_index_name()

# ---------- Elasticsearch setup ----------
es = Util.get_connection()
repo = FurnitureRepository(es, INDEX, force=True)  # Recreates index


# ---------- Helper ----------
def get_attribute_value(product, label):
    for attr in product.get("attributes", []):
        if attr.get("frontend_label") == label:
            value = attr.get("value", "").strip()
            return value if value else ""
    return ""


# ---------- Fetch products ----------
def fetch_products():
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "PostmanRuntime/7.31.3",
        "Origin": MY_BASE_URL,
        "Referer": MY_BASE_URL + "/"
    }

    session = requests.Session()
    session.headers.update(headers)

    all_items = []

    try:
        for page in range(1, 3):
            payload = {
                "currentPage": page,
                "pageSize": 100,
                "sort": "default",
                "lang": "en"
            }

            print(f"Requesting products (page {page})...")
            response = session.post(PRODUCT_SEARCH_ENDPOINT, json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()

            items = data.get("data", {}).get("products", {}).get("items", [])
            print(f"Fetched {len(items)} products from page {page}")

            all_items.extend(items)

            # Stop early if fewer than pageSize items returned
            if len(items) < 500:
                print("No more pages available. Stopping early.")
                break

        print(f"Total products fetched: {len(all_items)}")
        return all_items

    except requests.exceptions.RequestException as e:
        print(f"Error fetching products: {e}")
        return all_items

# ---------- Download ONLY the main original image ----------
def download_main_image(product, retries=3):
    main_image_url = product.get("image", {}).get("url")
    if not main_image_url:
        return ""

    # Clean filename
    dest_filename = Path(main_image_url).name.split("?")[0]
    if not dest_filename.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
        dest_filename += ".jpg"

    dest_path = UPLOAD_DIR / dest_filename

    if not dest_path.exists():
        attempt = 0
        while attempt <= retries:
            try:
                r = requests.get(main_image_url, stream=True, timeout=30)
                r.raise_for_status()
                with open(dest_path, "wb") as f:
                    shutil.copyfileobj(r.raw, f)
                # print(f"Downloaded main image: {dest_path}")
                break
            except Exception as e:
                attempt += 1
                if attempt > retries:
                    print(f"Failed to download {main_image_url}: {e}")
                else:
                    time.sleep(2 ** attempt)

    return f"uploads/{dest_filename}" if dest_path.exists() else ""


# ---------- Import products ----------
def import_products(products):
    items = []
    products_with_images = 0
    skipped_tableau = 0

    for product in products:

        if product.get("sub_category") == "Tableau":
            skipped_tableau += 1
            continue

        # Download only the main image
        image_path = download_main_image(product)
        if image_path:
            products_with_images += 1

        # Empty media_gallery (since you don't want extra images)
        media_gallery = []

        # Description - preserve HTML
        desc_obj = product.get("description", {})
        description = desc_obj.get("html", "") if isinstance(desc_obj, dict) else ""

        # Colors
        colors_str = get_attribute_value(product, "Colors")
        colors = [c.strip() for c in colors_str.split(",") if c.strip()] if colors_str else []

        # Item type
        item_type = product.get("item_type", "")
        if not item_type:
            item_type = product.get("sub_category", "")

        # Material
        material = get_attribute_value(product, "Detailed Materials")
        if not material:
            material = "Mixed"

        # Dimensions
        width = get_attribute_value(product, "Width (cm)")
        depth = get_attribute_value(product, "Depth (cm)") or get_attribute_value(product, "Length (cm)")
        height = get_attribute_value(product, "Height (cm)")
        dim_parts = [v for v in [width, depth, height] if v]
        dimensions = " x ".join(f"{v} cm" for v in dim_parts) if dim_parts else ""

        # Prices
        price_range = product.get("price_range", {}).get("minimum_price", {})
        regular_price = price_range.get("regular_price", {}).get("value") or 0
        final_price = price_range.get("final_price", {}).get("value")
        special_price = final_price if final_price and final_price != regular_price else None
        final_price = final_price or regular_price

        furniture = Furniture(
            sku=product.get("sku") or str(product.get("id")),
            item_name=product.get("name", "Unnamed Product"),
            material_value=material,
            item_type=item_type,
            colors=colors,
            dimensions=dimensions,
            price=regular_price,
            special_price=special_price,
            final_price=final_price,
            image_path=image_path,
            description=description,
            media_gallery=media_gallery  # Empty list
        )

        items.append(furniture)

    repo.bulk_insert(items, refresh=True)
    print(f"Total products processed: {len(products)}")
    print(f"Skipped Tableau products: {skipped_tableau}")
    print(f"Products with main image: {products_with_images}")
    print(f"Imported {len(items)} products into Elasticsearch.")


# ---------- Main ----------
if __name__ == "__main__":
    print(f"Using index: {INDEX}")

    products = fetch_products()

    if not products:
        print("No products fetched. Check your BASE_URL and network.")
    else:
        import_products(products)