from database import get_vendor_session
from datetime import datetime
import uuid

class BillService:
    def __init__(self):
        print("✅ BillService initialized")
    
    def create_bill(self, bill_data):
        """Create a bill in local database"""
        print(f"📝 Creating bill: {bill_data.get('bill_number')}")
        
        bill_id = uuid.uuid4()
        now = datetime.now()
        
        with get_vendor_session() as db:
            try:
                # Get raw DBAPI connection
                raw_connection = db.connection().connection
                cursor = raw_connection.cursor()
                
                cursor.execute("""
                    INSERT INTO bills (
                        id, invoice_id, invoice_number, contact_id, amount,
                        payment_mode, reference_number, payment_date, status, 
                        created_by, bill_number, payment_id, vendor_id, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    bill_id,
                    bill_data.get("invoice_id"),
                    bill_data.get("invoice_number"),
                    bill_data.get("contact_id"),
                    bill_data.get("amount"),
                    bill_data.get("payment_mode"),
                    bill_data.get("reference_number"),
                    bill_data.get("payment_date"),
                    bill_data.get("status", "open"),
                    bill_data.get("created_by"),
                    bill_data.get("bill_number"),
                    bill_data.get("payment_id"),
                    bill_data.get("vendor_id"),
                    now,
                    now
                ))
                
                raw_connection.commit()
                cursor.close()
                
                print(f"✅ Bill created: {bill_data.get('bill_number')}")
                
                return {
                    "id": bill_id,
                    "bill_number": bill_data.get("bill_number")
                }
                
            except Exception as e:
                print(f"❌ Error creating bill: {e}")
                import traceback
                traceback.print_exc()
                raise e
    
    def get_bills_for_customer(self, contact_id: str) -> list:
        """Get bills for a customer by contact_id"""
        print(f"🔍 Getting bills for contact_id: '{contact_id}'")
        
        with get_vendor_session() as db:
            try:
                raw_connection = db.connection().connection
                cursor = raw_connection.cursor()
                
                # Query for specific contact_id
                cursor.execute("""
                    SELECT * FROM bills 
                    WHERE contact_id = %s
                    ORDER BY created_at DESC
                """, (contact_id,))
                
                results = cursor.fetchall()
                cursor.close()
                
                print(f"📊 Found {len(results)} bills")
                
                bills = []
                for row in results:
                    # Map columns based on actual table structure
                    # 1: id, 2: invoice_id, 3: invoice_number, 4: contact_id, 5: amount,
                    # 6: payment_mode, 7: reference_number, 8: payment_date, 9: status,
                    # 10: created_by, 11: cts, 12: mts, 13: bill_number, 14: payment_id,
                    # 15: vendor_id, 16: created_at, 17: updated_at
                    bills.append({
                        "id": row[0],                    # id
                        "invoice_id": row[1],            # invoice_id
                        "invoice_number": row[2],        # invoice_number
                        "contact_id": row[3],            # contact_id
                        "amount": float(row[4]) if row[4] is not None else 0.0,  # amount
                        "payment_mode": row[5],          # payment_mode
                        "reference_number": row[6],      # reference_number
                        "payment_date": row[7],          # payment_date
                        "status": row[8],                # status
                        "created_by": row[9],            # created_by
                        "bill_number": row[12],          # bill_number (column 13)
                        "payment_id": row[13],           # payment_id (column 14)
                        "vendor_id": row[14],            # vendor_id (column 15)
                        "created_at": row[15],           # created_at (column 16)
                        "updated_at": row[16]            # updated_at (column 17)
                    })
                
                return bills
            except Exception as e:
                print(f"❌ Error fetching bills: {e}")
                import traceback
                traceback.print_exc()
                return []
    
    def get_bill(self, bill_id: str, contact_id: str):
        """Get a single bill"""
        with get_vendor_session() as db:
            try:
                raw_connection = db.connection().connection
                cursor = raw_connection.cursor()
                
                cursor.execute("""
                    SELECT * FROM bills 
                    WHERE id = %s AND contact_id = %s
                """, (bill_id, contact_id))
                
                result = cursor.fetchone()
                cursor.close()
                
                if not result:
                    return None
                
                return {
                    "id": result[0],
                    "invoice_id": result[1],
                    "invoice_number": result[2],
                    "contact_id": result[3],
                    "amount": float(result[4]) if result[4] is not None else 0.0,
                    "payment_mode": result[5],
                    "reference_number": result[6],
                    "payment_date": result[7],
                    "status": result[8],
                    "created_by": result[9],
                    "bill_number": result[12],
                    "payment_id": result[13],
                    "vendor_id": result[14],
                    "created_at": result[15],
                    "updated_at": result[16]
                }
            except Exception as e:
                print(f"❌ Error fetching bill: {e}")
                return None