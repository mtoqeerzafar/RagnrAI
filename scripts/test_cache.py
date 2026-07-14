import sys
import traceback
from cache.semantic_cache import SemanticCache

try:
    cache = SemanticCache()
    print("Testing check_cache...")
    res = cache.check_cache("hello")
    print(f"check_cache returned: {res}")
    
    print("Testing set_cache...")
    # Directly call the inner logic to see traceback
    import uuid
    point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "hello"))
    cache.client.add(
        collection_name=cache.collection_name,
        documents=["hello"],
        metadata=[{"answer": "world"}],
        ids=[point_id]
    )
    print("set_cache succeeded!")
except Exception as e:
    print("Exception caught:")
    traceback.print_exc()
