from bson.objectid import ObjectId
from pymongo.errors import ConfigurationError, ServerSelectionTimeoutError
from database import mongo_collection
from utils.serializers import serialize_document

class MongoService:
    
    @staticmethod
    def health_check():
            """
            Simple MongoDB health check.
            Returns True if the DB is reachable.
            """
            try:
                # Ping command to check connection
                mongo_collection.database.command("ping")
                return {"status": "ok", "message": "MongoDB connection healthy"}
            except ServerSelectionTimeoutError:
                return {"status": "error", "message": "MongoDB unreachable"}
            except ConfigurationError as e:
                return {"status": "error", "message": f"MongoDB configuration error: {str(e)}"}
            except Exception as e:
                return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @staticmethod
    def list_all():
        try:
            return [serialize_document(d) for d in mongo_collection.find()]
        except ConfigurationError as e:
            raise RuntimeError("Mongo incompatible: " + str(e))
        except ServerSelectionTimeoutError:
            raise RuntimeError("Mongo unreachable")

    @staticmethod
    def get_one(doc_id: str):
        oid = ObjectId(doc_id)
        doc = mongo_collection.find_one({"_id": oid})
        if not doc:
            raise ValueError("Document not found")
        return serialize_document(doc)

    @staticmethod
    def insert(payload: dict):
        result = mongo_collection.insert_one(payload)
        return {"id": str(result.inserted_id)}

    @staticmethod
    def update(doc_id: str, payload: dict):
        oid = ObjectId(doc_id)

        if not mongo_collection.find_one({"_id": oid}):
            raise ValueError("Document not found")

        mongo_collection.update_one({"_id": oid}, {"$set": payload})
        return {"id": doc_id}

    @staticmethod
    def delete(doc_id: str):
        oid = ObjectId(doc_id)

        if not mongo_collection.find_one({"_id": oid}):
            raise ValueError("Document not found")

        mongo_collection.delete_one({"_id": oid})
        return {"id": doc_id}
