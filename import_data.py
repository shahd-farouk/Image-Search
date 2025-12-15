import os
import re
import shutil
from pathlib import Path
from furniture import Furniture, FurnitureRepository, Util
from PIL import Image

DATA_FOLDER = Path("data")
UPLOAD_DIR = Path("static/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

es = Util.get_connection()
INDEX = Util.get_index_name()
repo = FurnitureRepository(es, INDEX)


def parse_metadata(meta_path):
    with open(meta_path, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f.readlines() if l.strip()]

    item_name = lines[0]
    metadata = {
        "item_name": item_name,
        "material": "unknown",
        "item_type": "",
        "width": None,
        "height": None,
        "colors": [],
        "description": "",
    }

    for line in lines[1:]:
        if line.startswith("Material:"):
            metadata["material"] = line.replace("Material:", "").strip()
        elif line.startswith("Item_Type:"):
            metadata["item_type"] = line.replace("Item_Type:", "").strip()
        elif line.startswith("Width"):
            match = re.search(r"([\d.]+)", line)
            if match:
                metadata["width"] = float(match.group(1))
        elif line.startswith("Height"):
            match = re.search(r"([\d.]+)", line)
            if match:
                metadata["height"] = float(match.group(1))
        elif line.startswith("Colors:"):
            metadata["colors"] = [c.strip() for c in line.replace("Colors:", "").split(",")]

    metadata["description"] = f"{metadata['material']} {metadata['item_type']}"
    return metadata


def find_images(folder_path):
    return [
        file
        for file in folder_path.iterdir()
        if file.is_file()
        and file.stem.lower() == "original"
        and file.suffix.lower() in [".jpg", ".jpeg", ".png"]
        ]

def reset_index():
    if es.indices.exists(index=INDEX):
        es.indices.delete(index=INDEX)
        print(f"Deleted index: {INDEX}")
    else:
        print(f"Index does not exist: {INDEX}")

def import_all():
    for folder in DATA_FOLDER.iterdir():
        if not folder.is_dir():
            continue

        meta_file = folder / "metadata.txt"
        if not meta_file.exists():
            print(f"No metadata found in {folder}, skipping...")
            continue

        metadata = parse_metadata(meta_file)
        images = find_images(folder)
        if not images:
            print(f"No images found in {folder}, skipping...")
            continue

        for img_path in images:
            dest_filename = f"{metadata['item_name'].replace(' ', '_')}_{img_path.name}"
            dest_path = UPLOAD_DIR / dest_filename
            shutil.copy(img_path, dest_path)

            f = Furniture(
                item_name=metadata["item_name"],
                material=metadata["material"],
                item_type=metadata["item_type"],
                width=metadata["width"],
                height=metadata["height"],
                colors=metadata["colors"],
                image_path=str(dest_path),
                description=metadata["description"]
            )
            f.generate_embeddings()

            f.image_path = f"/static/uploads/{dest_filename}"

            repo.insert(f)


if __name__ == "__main__":
    reset_index()
    import_all()