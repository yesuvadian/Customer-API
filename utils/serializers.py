from bson.objectid import ObjectId
from bson.binary import Binary
import base64

def _serialize_value(val):
    if isinstance(val, ObjectId):
        return str(val)
    if isinstance(val, (bytes, bytearray, memoryview, Binary)):
        return base64.b64encode(bytes(val)).decode("ascii")
    if isinstance(val, dict):
        return {k: _serialize_value(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [_serialize_value(v) for v in val]
    return val

def serialize_document(doc):
    return _serialize_value(doc)
