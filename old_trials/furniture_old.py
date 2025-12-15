# furniture_es.py
import os
import re
import traceback
from pathlib import Path
from typing import List, Dict, Optional

from PIL import Image
from sentence_transformers import SentenceTransformer
from elasticsearch import Elasticsearch, exceptions as es_exceptions

# ---------- Configuration ----------
DEFAULT_INDEX = os.environ.get("ES_INDEX", "hybrid-index")
ES_CLOUD_ID = os.environ.get("ES_CLOUD_ID")  # optional
ES_USER = os.environ.get("ES_USER")
ES_PASS = os.environ.get("ES_PASS")
ES_HOST = os.environ.get("ES_HOST")  # for non-cloud usage, e.g. "http://localhost:9200"
# -----------------------------------

class Util:
    @staticmethod
    def get_index_name():
        return DEFAULT_INDEX

    @staticmethod
    def get_connection():
        if ES_CLOUD_ID and ES_USER and ES_PASS:
            es = Elasticsearch(cloud_id=ES_CLOUD_ID, basic_auth=(ES_USER, ES_PASS))
        elif ES_HOST and ES_USER and ES_PASS:
            es = Elasticsearch(ES_HOST, basic_auth=(ES_USER, ES_PASS))
        else:
            # fallback to local
            es = Elasticsearch("http://localhost:9200")
        # quick ping / info
        try:
            es.info()
        except Exception as e:
            raise RuntimeError(f"Elasticsearch unreachable: {e}")
        return es

    @staticmethod
    def create_index(es: Elasticsearch, index_name: str, target_dim=512, text_dim=None, image_dim=None, force_recreate: bool = False):
        if text_dim is None:
            text_dim = target_dim
        if image_dim is None:
            image_dim = target_dim

        index_config = {
            "settings": {
                "index.refresh_interval": "5s",
                "number_of_shards": 1
            },
            "mappings": {
                "properties": {
                    "item_name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                    "material": {"type": "keyword"},
                    "item_type": {"type": "keyword"},
                    "width": {"type": "float"},
                    "height": {"type": "float"},
                    "colors": {"type": "keyword"},
                    "image_path": {"type": "keyword"},
                    "description": {"type": "text"},
                    "text_embedding": {
                        "type": "dense_vector",
                        "dims": int(text_dim),
                        "index": True,
                        "similarity": "cosine"
                    },
                    "image_embedding": {
                        "type": "dense_vector",
                        "dims": int(image_dim),
                        "index": True,
                        "similarity": "cosine"
                    },
                    "exif": {
                        "properties": {
                            "location": {"type": "geo_point"},
                            "date": {"type": "date"}
                        }
                    }
                }
            }
        }

        # delete if exists and force_recreate requested
        if force_recreate:
            es.indices.delete(index=index_name, ignore_unavailable=True)

        try:
            if not es.indices.exists(index=index_name):
                es.indices.create(index=index_name, body=index_config)
                print(f"Created index: {index_name}")
            else:
                print(f"Index already exists: {index_name}")
        except Exception as e:
            print("Error creating index:", e)
            raise

    @staticmethod
    def delete_index(es: Elasticsearch, index_name: str):
        es.indices.delete(index=index_name, ignore_unavailable=True)

# ---------- domain (Furniture) ----------
class Furniture:
    # Use CLIP via sentence-transformers
    model = SentenceTransformer('clip-ViT-B-32')

    def __init__(self, item_name: str, material: str, item_type: str, width: Optional[float],
                 height: Optional[float], colors, image_path: str, description: str = None):
        self.item_name = item_name
        self.material = material
        self.item_type = item_type
        self.width = float(width) if width is not None else None
        self.height = float(height) if height is not None else None

        if isinstance(colors, str):
            parsed = [c.strip() for c in re.split(r',|\||;', colors) if c.strip()]
            self.colors = parsed if parsed else [colors]
        elif isinstance(colors, (list, tuple)):
            self.colors = list(colors)
        else:
            self.colors = [str(colors)]

        self.image_path = image_path
        self.description = description
        self.image_embedding = None
        self.text_embedding = None

    @staticmethod
    def encode_image_from_path(image_path: str):
        image = Image.open(image_path).convert("RGB")
        emb = Furniture.model.encode(image)
        return emb.astype(float).tolist()

    @staticmethod
    def encode_text(text: str):
        emb = Furniture.model.encode(text)
        return emb.astype(float).tolist()

    def generate_embeddings(self):
        if self.image_path:
            self.image_embedding = Furniture.encode_image_from_path(self.image_path)
        if self.description:
            self.text_embedding = Furniture.encode_text(self.description)

    def to_dict(self):
        body = {
            'item_name': self.item_name,
            'material': self.material,
            'item_type': self.item_type,
            'width': self.width,
            'height': self.height,
            'colors': self.colors,
            'image_path': self.image_path,
            'description': self.description,
            'image_embedding': self.image_embedding
        }
        if self.text_embedding is not None:
            body['text_embedding'] = self.text_embedding
        return body

# ---------- repository ----------
class FurnitureRepository:
    def __init__(self, es_client: Elasticsearch, index_name: str):
        self.es_client = es_client
        self._index_name = index_name
        # ensure index exists
        Util.create_index(es_client, index_name)

    def insert(self, furniture: Furniture):
        if furniture.image_embedding is None and furniture.image_path:
            furniture.generate_embeddings()
        body = furniture.to_dict()
        self.es_client.index(index=self._index_name, document=body)

    def bulk_insert(self, furniture_items: List[Furniture], refresh: bool = False):
        operations = []
        for item in furniture_items:
            if item.image_embedding is None and item.image_path:
                item.generate_embeddings()
            operations.append({"index": {"_index": self._index_name}})
            operations.append(item.to_dict())
        self.es_client.bulk(body=operations, refresh='true' if refresh else 'false')

    def search_by_knn(self, field: str, vector: List[float], k: int = 5, source_fields: List[str] = None):
        if source_fields is None:
            source_fields = ["item_name", "material", "item_type", "width", "height", "colors", "image_path", "description"]

        knn = {
            "field": field,
            "k": k,
            "num_candidates": 100,
            "query_vector": vector,
        }

        try:
            resp = self.es_client.search(
                index=self._index_name,
                body={
                    "size": k,
                    "knn": knn,
                    "_source": source_fields
                }
            )
            return resp
        except Exception as e:
            print("Search error:", e)
            return {"hits": {"hits": []}}

    def fetch_all_items(self, size: int = 1000):
        try:
            resp = self.es_client.search(index=self._index_name, body={"size": size, "query": {"match_all": {}}})
            return resp.get('hits', {}).get('hits', [])
        except Exception as e:
            print("Fetch error:", e)
            return []