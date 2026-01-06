import asyncpg
from config import POSTGRES_CONFIG
from datetime import datetime

class ERPService:
    pool = None
    ERP_AVAILABLE = True

    STARTING_ID = int(f"{datetime.utcnow().year}{datetime.utcnow().month:02d}0000001")


    # ==================================================
    # SAFE INIT POOL (Never crashes)
    # ==================================================
    @classmethod
    async def init_pool(cls):
        """
        Backward compatible — but NOT safe.
        Used only if ERP_AVAILABLE is True.
        """
        if not cls.ERP_AVAILABLE:
            return False

        if cls.pool is not None:
            return True

        cls.pool = await asyncpg.create_pool(**POSTGRES_CONFIG)
        return True
    @classmethod
    async def get_or_create_hsncode_id(cls, hsn_code: str, hsndesc: str = None) -> int:
        """
        Get or create HSN code in ERP.
        If exists, returns hsncodesid.
        If not, generates a new ID, inserts, and returns it.
        """
        if not hsn_code:
            raise ValueError("hsn_code is required")

        if not await cls.safe_init_pool():
            raise Exception("ERP unavailable")

        hsndesc = hsndesc or hsn_code

        async with cls.pool.acquire() as conn:
            async with conn.transaction():
                # Check if already exists
                result = await conn.fetchrow(
                    'SELECT "hsncodesid" FROM "hsncodes" WHERE "hsncode"=$1',
                    hsn_code
                )
                if result:
                    return result["hsncodesid"]

                # Generate unique ID
                # Using STARTING_ID as base; could also have separate sequence for HSN if desired
                #prefix = str(cls.STARTING_ID)[:4]
                max_id = await conn.fetchval(
                    f'''
                    SELECT MAX(CAST("hsncodesid" AS BIGINT))
                    FROM "hsncodes"
                    WHERE "hsncodesid" IS NOT NULL
                  
                    '''
                )
                next_id = max_id + 1 if max_id else cls.STARTING_ID

                # Insert new record
                await conn.execute(
                    'INSERT INTO "hsncodes" ("hsncodesid", "hsncode", "hsndesc", "activeyn") VALUES ($1, $2, $3, "YES")',
                    next_id,
                    hsn_code,
                    hsndesc,
                    activeyn
                )
                return next_id


    @classmethod
    async def safe_init_pool(cls):
        """
        New safe initializer:
        - never raises exception
        - returns True if connected
        - returns False if failed
        """
        if not cls.ERP_AVAILABLE:
            return False

        if cls.pool is not None:
            return True

        try:
            cls.pool = await asyncpg.create_pool(**POSTGRES_CONFIG)
            print("✅ ERP PostgreSQL Pool initialized.")
            return True

        except Exception as e:
            print(f"⚠️ ERP PostgreSQL unavailable: {e}")
            cls.pool = None
            cls.ERP_AVAILABLE = False
            return False


    # ==================================================
    # HEALTH CHECK
    # ==================================================
    @classmethod
    async def health(cls):
        if not cls.ERP_AVAILABLE or cls.pool is None:
            return {"status": "error", "message": "ERP database unavailable"}

        try:
            async with cls.pool.acquire() as conn:
                ping = await conn.fetchval("SELECT 1")
            return {
                "status": "success",
                "message": "PostgreSQL healthy",
                "data": {"ping": ping}
            }
        except Exception as e:
            cls.pool = None
            cls.ERP_AVAILABLE = False
            return {"status": "error", "message": str(e)}


    # ==================================================
    # UTILITY: process row data
    # ==================================================
    @staticmethod
    def process_row_data(row: dict, id_fields: list):
        cols = []
        vals = []
        for k, v in row.items():
            cols.append(f'"{k}"')
            vals.append(v)
        return cols, vals

    @classmethod
    async def insert_item_with_tax(cls, items: list):
        """
        Inserts itemmaster + itemtax in ONE transaction.
        items = [
            {
                "itemmaster": {...},
                "itemtax": {...}
            }
        ]
        """
        if not items:
            return []

        # 🔒 Validation
        for idx, item in enumerate(items):
            if "itemmaster" not in item:
                raise ValueError(f"itemmaster missing at index {idx}")

            if "itemtax" in item:
                if "igstper" not in item["itemtax"]:
                    raise ValueError("GST % missing")
                if "hsncode" not in item["itemtax"]:
                    raise ValueError("HSN Code missing")

        # 🚀 Delegate to generic insert
        return await cls.insert_data(items)
    # ==================================================
    # INSERT LOGIC (unchanged)
    # ==================================================
    @classmethod
    async def insert_data(cls, payload: list):
        if not await cls.safe_init_pool():
            raise Exception("ERP unavailable")

        # ... your original insert code unchanged ...
        # (keep everything exactly as you pasted)

        # PASTE EVERYTHING FROM HERE DOWN
        first_item = payload[0]
        table_names = list(first_item.keys())

        parent_table = table_names[0]
        id_field_name = f"{parent_table}id"
        child_tables = table_names[1:]
        table_order = [parent_table] + child_tables

        async with cls.pool.acquire() as conn:
            async with conn.transaction():

                prefix = str(cls.STARTING_ID)[:4]

                max_id = await conn.fetchval(
                    f'''
                    SELECT MAX(CAST("{id_field_name}" AS BIGINT))
                    FROM "{parent_table}"
                    WHERE "{id_field_name}" IS NOT NULL
                    AND substring(CAST("{id_field_name}" AS TEXT), 1, 4) = '{prefix}'
                    '''
                )

                next_id = max_id + 1 if max_id else cls.STARTING_ID

                all_inserts = {table: [] for table in table_order}
                id_to_index = {}
                results = [{} for _ in payload]

                for idx, item in enumerate(payload):
                    generated_id = next_id
                    next_id += 1
                    id_to_index[generated_id] = idx

                    for table_name in table_order:
                        if table_name not in item:
                            continue

                        row = item[table_name].copy()
                        row[id_field_name] = generated_id

                        if table_name in child_tables:
                            row[f"{table_name}id"] = generated_id

                        id_fields = [id_field_name]
                        if table_name in child_tables:
                            id_fields.append(f"{table_name}id")

                        cols, vals = cls.process_row_data(row, id_fields)

                        if cols:
                            all_inserts[table_name].append((cols, vals))

                for table_name in table_order:
                    grouped = {}

                    for cols, vals in all_inserts[table_name]:
                        grouped.setdefault(tuple(cols), []).append(vals)

                    for cols, values_list in grouped.items():
                        col_str = ", ".join(cols)
                        num_cols = len(cols)

                        placeholders = []
                        p = 1
                        for _ in values_list:
                            placeholders.append(
                                "(" + ", ".join(f'${p + i}' for i in range(num_cols)) + ")"
                            )
                            p += num_cols

                        sql = f'''
                            INSERT INTO "{table_name}" ({col_str})
                            VALUES {", ".join(placeholders)}
                            RETURNING *
                        '''

                        flat_vals = [v for row in values_list for v in row]
                        rows = await conn.fetch(sql, *flat_vals)

                        for r in rows:
                            rec = dict(r)
                            results[id_to_index[rec[id_field_name]]][table_name] = rec

        return results


    # ==================================================
    # UPDATE LOGIC (unchanged)
    # ==================================================
    @classmethod
    async def update_data(cls, payload: list):
        if not await cls.safe_init_pool():
            raise Exception("ERP unavailable")

        # keep all your original update logic EXACTLY as-is...
        first_item = payload[0]
        table_names = list(first_item.keys())

        parent_table = table_names[0]
        id_field_name = f"{parent_table}id"
        child_tables = table_names[1:]
        table_order = [parent_table] + child_tables

        async with cls.pool.acquire() as conn:
            async with conn.transaction():

                results = [{} for _ in payload]

                for idx, item in enumerate(payload):

                    if id_field_name not in item[parent_table]:
                        raise Exception(f"{id_field_name} missing")

                    record_id = item[parent_table][id_field_name]

                    exists = await conn.fetchval(
                        f'SELECT 1 FROM "{parent_table}" WHERE "{id_field_name}"=$1',
                        record_id
                    )

                    if not exists:
                        raise Exception(f"Record {record_id} not found")

                    for table_name in table_order:
                        if table_name not in item:
                            continue

                        row = item[table_name].copy()
                        row[id_field_name] = record_id

                        if table_name in child_tables:
                            row[f"{table_name}id"] = record_id

                        id_fields = [id_field_name]
                        if table_name in child_tables:
                            id_fields.append(f"{table_name}id")

                        cols, vals = cls.process_row_data(row, id_fields)

                        set_parts = []
                        params = []
                        p = 1

                        for c, v in zip(cols, vals):
                            c_name = c.replace('"', '')
                            if c_name in id_fields:
                                continue
                            set_parts.append(f"{c}=${p}")
                            params.append(v)
                            p += 1

                        if not set_parts:
                            rec = await conn.fetchrow(
                                f'SELECT * FROM "{table_name}" WHERE "{id_field_name}"=$1',
                                record_id
                            )
                            results[idx][table_name] = dict(rec)
                            continue

                        sql = f'''
                            UPDATE "{table_name}"
                            SET {", ".join(set_parts)}
                            WHERE "{id_field_name}"=${p}
                            RETURNING *
                        '''

                        params.append(record_id)
                        rec = await conn.fetchrow(sql, *params)

                        results[idx][table_name] = dict(rec)

        return results
