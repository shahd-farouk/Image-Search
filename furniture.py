import os
import re
import warnings
from PIL import Image
from pathlib import Path
from typing import List, Optional
from elasticsearch import Elasticsearch

warnings.filterwarnings("ignore", category=UserWarning)

# ---------- Configuration ----------
DEFAULT_INDEX = os.environ.get("ES_INDEX", "products_en")
ES_CLOUD_ID = os.environ.get("ES_CLOUD_ID")
ES_USER = os.environ.get("ES_USER")
ES_PASS = os.environ.get("ES_PASS")
ES_HOST = os.environ.get("ES_HOST", "http://localhost:9200")

# ---------- Utilities ----------
class Util:
    @staticmethod
    def get_index_name():
        return DEFAULT_INDEX

    @staticmethod
    def get_connection():
        if ES_CLOUD_ID and ES_USER and ES_PASS:
            es = Elasticsearch(cloud_id=ES_CLOUD_ID, basic_auth=(ES_USER, ES_PASS))
        elif ES_USER and ES_PASS:
            es = Elasticsearch(ES_HOST, basic_auth=(ES_USER, ES_PASS))
        else:
            es = Elasticsearch(ES_HOST)

        es.info()  # fail fast if ES is unreachable
        return es

    @staticmethod
    def create_index(es: Elasticsearch, index_name: str, dim: int = 512, force: bool = False):
        if force:
            es.indices.delete(index=index_name, ignore_unavailable=True)

        if es.indices.exists(index=index_name):
            return

        es.indices.create(
            index=index_name,
            body={
                "settings": {"number_of_shards": 1},
                "mappings": {
                    "properties": {
                        "sku": {"type": "keyword"},
                        "item_name": {"type": "text"},
                        "description": {"type": "text"},
                        "material_value": {"type": "keyword"},
                        "item_type": {"type": "keyword"},
                        "colors": {"type": "keyword"},
                        "dimensions": {"type": "keyword"},
                        "price": {"type": "float"},
                        "special_price": {"type": "float"},
                        "final_price": {"type": "float"},
                        "image_path": {"type": "keyword"},
                        "media_gallery": {
                            "type": "nested",
                            "properties": {
                                "id": {"type": "integer"},
                                "media_type": {"type": "keyword"},
                                "file": {"type": "keyword"},
                                "position": {"type": "integer"},
                                "disabled": {"type": "boolean"},
                                "types": {"type": "keyword"}
                            }
                        },
                        "text_embedding": {
                            "type": "dense_vector",
                            "dims": dim,
                            "index": True,
                            "similarity": "cosine"
                        },
                        "image_embedding": {
                            "type": "dense_vector",
                            "dims": dim,
                            "index": True,
                            "similarity": "cosine"
                        }
                    }
                }
            }
        )

# ---------- Domain Model ----------
class Furniture:
    _model = None

    def __init__(
        self,
        sku: str,
        item_name: str,
        material_value: str,
        item_type: str,
        colors,
        dimensions: str,
        price: float,
        special_price: Optional[float],
        final_price: float,
        image_path: str,
        description: Optional[str] = None,
        media_gallery: Optional[List[dict]] = None
    ):
        self.sku = sku
        self.item_name = item_name
        self.material_value = material_value
        self.item_type = item_type
        self.colors = self._parse_colors(colors)
        self.dimensions = dimensions
        self.price = price
        self.special_price = special_price
        self.final_price = final_price
        self.image_path = image_path
        self.description = description or f"{material_value} {item_type}"
        self.media_gallery = media_gallery or []
        self.image_embedding = None
        self.text_embedding = None

    @staticmethod
    def get_model():
        if Furniture._model is None:
            from sentence_transformers import SentenceTransformer
            print("Loading CLIP model...")
            Furniture._model = SentenceTransformer("clip-ViT-B-32")
            print("CLIP model loaded.")
        return Furniture._model

    @staticmethod
    def _parse_colors(colors):
        if isinstance(colors, str):
            return [c.strip() for c in re.split(r",|\||;", colors) if c.strip()]
        if isinstance(colors, (list, tuple)):
            return list(colors)
        return []

    def generate_embeddings(self):
        model = Furniture.get_model()

        if self.image_path:
            img_path = Path("static") / self.image_path
            image = Image.open(img_path).convert("RGB")
            self.image_embedding = model.encode(image).astype(float).tolist()

        if self.description:
            self.text_embedding = model.encode(self.description).astype(float).tolist()

    def to_dict(self):
        return {
            "sku": self.sku,
            "item_name": self.item_name,
            "material_value": self.material_value,
            "item_type": self.item_type,
            "colors": self.colors,
            "dimensions": self.dimensions,
            "price": self.price,
            "special_price": self.special_price,
            "final_price": self.final_price,
            "image_path": self.image_path,
            "description": self.description,
            "media_gallery": self.media_gallery,
            "image_embedding": self.image_embedding,
            "text_embedding": self.text_embedding
        }

# ---------- Repository ----------
class FurnitureRepository:
    def __init__(self, es: Elasticsearch, index_name: str, force: bool = False):
        Util.create_index(es, index_name, force=force)
        self.es = es
        self.index = index_name

    def insert(self, item: Furniture):
        item.generate_embeddings()
        self.es.index(index=self.index, id=item.sku, document=item.to_dict())

    def bulk_insert(self, items: List[Furniture], refresh: bool = False):
        ops = []
        for item in items:
            item.generate_embeddings()
            ops.append({"index": {"_index": self.index, "_id": item.sku}})
            ops.append(item.to_dict())
        self.es.bulk(body=ops, refresh=refresh)

    def search_by_knn(
        self,
        field: str,
        vector: List[float],
        k: int = 5,
        source_fields: List[str] = None
    ):
        if source_fields is None:
            source_fields = [
                "sku", "item_name", "material_value", "item_type",
                "colors", "dimensions", "price", "special_price",
                "final_price", "image_path", "description", "media_gallery"
            ]

        query = {
            "knn": {
                "field": field,
                "query_vector": vector,
                "k": k,
                "num_candidates": max(100, k * 10)
            },
            "size": k,
            "_source": source_fields
        }

        try:
            print(f"Running KNN search on {field} with k={k}, vector len={len(vector)}")
            result = self.es.search(index=self.index, body=query)
            print(f"KNN returned {len(result['hits']['hits'])} hits")
            return result
        except Exception as e:
            print("KNN search error:", e)
            import traceback
            traceback.print_exc()
            return {"hits": {"hits": []}}