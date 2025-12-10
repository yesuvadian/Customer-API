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




def sanitize_for_mongo(data):
    """
    Convert data into MongoDB-safe format:
    - memoryview → bytes
    - bytes → Binary
    """
    if isinstance(data, dict):
        return {k: sanitize_for_mongo(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_for_mongo(v) for v in data]
    elif isinstance(data, memoryview):
        return Binary(data.tobytes())
    elif isinstance(data, bytes):
        return Binary(data)
    else:
        return data


def serialize_document(doc: dict):
    """
    Convert MongoDB BSON → JSON safe format.
    Ensures:
    - ObjectId -> string
    - Binary -> {"$binary": "<base64>"}
    """
    result = {}

    for key, value in doc.items():

        if isinstance(value, ObjectId):
            result[key] = str(value)

        elif isinstance(value, Binary):
            # Convert real binary → Base64 and maintain correct structure
            result[key] = {
                "$binary": base64.b64encode(value).decode()
            }

        else:
            result[key] = value

    return result
