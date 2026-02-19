import json
from fastapi import HTTPException, status, Response
from pydantic import BaseModel, Field
from typing import Optional
import config
from services.zoho_client import zoho_request
from services.redis_cache import RedisCacheService as cache


# ─────────────────────────────────────────
# Sub-models
# ─────────────────────────────────────────

class ItemLocation(BaseModel):
    """
    Per-location initial stock settings.
    Pass one entry per Zoho location when initial_stock tracking is needed.
    """
    location_id: str = Field(..., description="Zoho location ID")
    initial_stock: Optional[float] = Field(None, description="Opening stock quantity at this location")
    initial_stock_rate: Optional[float] = Field(None, description="Opening stock value per unit at this location")


class ItemTaxPreference(BaseModel):
    """
    Used for GST (India) intra/inter tax splitting.
    Supply when the item needs separate intra-state and inter-state tax IDs.
    """
    tax_id: str = Field(..., description="Zoho tax ID")
    tax_specification: Optional[str] = Field(
        None,
        description="Tax scope. Allowed values: 'intra', 'inter'",
    )


class CustomField(BaseModel):
    """Key/value pair for Zoho custom fields attached to the item."""
    customfield_id: str = Field(..., description="Zoho custom field ID, e.g. '46000000012845'")
    value: str = Field(..., description="Value to set for this custom field")


# ─────────────────────────────────────────
# Main Request Model  (POST /items)
# ─────────────────────────────────────────

class CreateItemRequest(BaseModel):
    """
    Fields sourced from Zoho Books API v3 — Items (Create an Item).
    https://www.zoho.com/books/api/v3/items/#create-an-item

    Only `name` is required by Zoho. All other fields are optional.
    None values are stripped before the request is forwarded so Zoho does not
    reject the payload with unexpected null entries.
    """

    # ── Core ──────────────────────────────
    name: str = Field(
        ...,
        max_length=100,
        description="Name of the item. Max length: 100 characters.",
    )
    description: Optional[str] = Field(
        None,
        max_length=2000,
        description="Description for the item. Max length: 2000 characters.",
    )
    rate: Optional[float] = Field(
        None,
        description="Sales/unit price of the item.",
    )
    unit: Optional[str] = Field(
        None,
        description="Unit of measurement, e.g. 'pcs', 'kg', 'hrs'.",
    )
    sku: Optional[str] = Field(
        None,
        description="Stock Keeping Unit — must be unique across all items.",
    )

    # ── Classification ────────────────────
    product_type: Optional[str] = Field(
        None,
        description=(
            "Type of the product. "
            "Allowed values: 'goods', 'service'. "
            "For South Africa: also 'capital_goods', 'capital_service'."
        ),
    )
    item_type: Optional[str] = Field(
        None,
        description=(
            "Inventory tracking type. "
            "Allowed values: 'sales', 'purchases', 'sales_and_purchases', 'inventory'."
        ),
    )

    # ── Tax ───────────────────────────────
    tax_id: Optional[str] = Field(
        None,
        description="Zoho tax ID to associate with this item. Use GET /settings/taxes to look up IDs.",
    )
    is_taxable: Optional[bool] = Field(
        None,
        description="Whether the item is taxable.",
    )
    tax_exemption_id: Optional[str] = Field(
        None,
        description="Tax exemption ID (for non-taxable items).",
    )
    purchase_tax_exemption_id: Optional[str] = Field(
        None,
        description="Purchase-side tax exemption ID.",
    )
    purchase_tax_rule_id: Optional[str] = Field(
        None,
        description="Purchase tax rule ID (region-specific).",
    )
    sales_tax_rule_id: Optional[str] = Field(
        None,
        description="Sales tax rule ID (region-specific).",
    )
    item_tax_preferences: Optional[list[ItemTaxPreference]] = Field(
        None,
        description="GST intra/inter tax preferences. Used primarily for India GST.",
    )

    # ── Accounts ──────────────────────────
    account_id: Optional[str] = Field(
        None,
        description="Zoho GL sales account ID for this item.",
    )
    purchase_account_id: Optional[str] = Field(
        None,
        description="Zoho GL purchase/COGS account ID for this item.",
    )
    inventory_account_id: Optional[str] = Field(
        None,
        description="Zoho GL inventory asset account ID. Required when item_type is 'inventory'.",
    )

    # ── Purchase info ─────────────────────
    purchase_description: Optional[str] = Field(
        None,
        description="Description shown to vendors on purchase orders.",
    )
    purchase_rate: Optional[float] = Field(
        None,
        description="Purchase price / cost per unit.",
    )

    # ── Inventory / stock ─────────────────
    reorder_level: Optional[float] = Field(
        None,
        description="Stock level at which a reorder alert is triggered.",
    )
    locations: Optional[list[ItemLocation]] = Field(
        None,
        description="Per-location initial stock. Pass when item_type is 'inventory'.",
    )

    # ── Vendor ────────────────────────────
    vendor_id: Optional[str] = Field(
        None,
        description="Preferred vendor ID for purchasing this item.",
    )

    # ── Product identifiers ───────────────
    upc: Optional[str] = Field(
        None,
        description="12-digit Universal Product Code.",
    )
    ean: Optional[str] = Field(
        None,
        description="European Article Number (barcode).",
    )
    isbn: Optional[str] = Field(
        None,
        description="International Standard Book Number.",
    )
    part_number: Optional[str] = Field(
        None,
        description="Manufacturer part number.",
    )

    # ── Regional / compliance ─────────────
    hsn_or_sac: Optional[str] = Field(
        None,
        description="HSN (goods) or SAC (services) code for India GST compliance.",
    )
    sat_item_key_code: Optional[str] = Field(
        None,
        description="SAT item key code for Mexico CFDI e-invoicing.",
    )
    unitkey_code: Optional[str] = Field(
        None,
        description="SAT unit key code for Mexico CFDI e-invoicing.",
    )
    avatax_tax_code: Optional[str] = Field(
        None,
        description="Avalara AvaTax product tax code.",
    )
    avatax_use_code: Optional[str] = Field(
        None,
        description="Avalara AvaTax use/exemption code.",
    )

    # ── Custom shortcut fields ─────────────
    cf_utility: Optional[str] = Field(
        None,
        description="Utility type: Generation, Transmission, or DISCOM. Maps to Zoho custom field 'cf_utility'.",
    )
    cf_item_category: Optional[str] = Field(
        None,
        description="Free-text item category. Maps to Zoho custom field 'cf_item_category'.",
    )

    # ── Custom fields ─────────────────────
    custom_fields: Optional[list[CustomField]] = Field(
        None,
        description="Arbitrary custom field values configured in your Zoho Books org.",
    )


# ─────────────────────────────────────────
# Service
# ─────────────────────────────────────────

class ZohoItemService:

    # -----------------------------
    # Get Items (CACHED)
    # -----------------------------
    def get_items(self, search_text: str | None = None):
        search_key = search_text or "all"
        cache_key = f"zoho:items:all:{search_key}"

        cached = cache.get(cache_key)
        if cached:
            return cached

        all_items = []
        page = 1

        while True:
            params = {
                "organization_id": config.ZOHO_ORG_ID,
                "page": page,
                "per_page": 200,
                "filter_by": "Status.Active",
            }

            if search_text:
                params["search_text"] = search_text

            response = zoho_request("GET", "/items", params=params)

            if response.status_code != 200:
                raise HTTPException(status_code=400, detail=response.json())

            data = response.json()
            items = data.get("items", [])
            all_items.extend(items)

            page_context = data.get("page_context", {})

            if not page_context.get("has_more_page"):
                break

            page += 1
        

        # Sort alphabetically by name (case-insensitive)
        # ✅ Safe alphabetical sort
        all_items = sorted(
        all_items,
        key=lambda x: x.get("name", "").strip().lower()
        )

        result = {"items": all_items}
        cache.set(cache_key, result)

        return result



    # -----------------------------
    # Create Item + Bust Cache
    # -----------------------------
    def create_item(self, payload: CreateItemRequest):
        """
        Create a new item in Zoho Books via POST /items.
        Ref: https://www.zoho.com/books/api/v3/items/#create-an-item
        OAuth scope required: ZohoBooks.settings.CREATE
        Invalidates all cached item listings after a successful create.
        """
        print("\n===== ZOHO CREATE ITEM PAYLOAD =====")
      
        print("===================================\n")
        params = {"organization_id": config.ZOHO_ORG_ID}

        # Strip None values — Zoho rejects unexpected null fields
        # Strip None values
        body = payload.model_dump(exclude_none=True)

        # ---- CUSTOM FIELD MAPPING (MUST BE HERE) ----
        CUSTOM_FIELD_IDS = {
            "cf_utility": "2789833000000858001",
            "cf_item_category": "2789833000000267011",
        }

        custom_fields = []

        if "cf_utility" in body:
            custom_fields.append({
                "customfield_id": CUSTOM_FIELD_IDS["cf_utility"],
                "value": body.pop("cf_utility")
            })

        if "cf_item_category" in body:
            custom_fields.append({
                "customfield_id": CUSTOM_FIELD_IDS["cf_item_category"],
                "value": body.pop("cf_item_category")
            })

        if custom_fields:
            body["custom_fields"] = custom_fields
# --------------------------------------------


       

        response = zoho_request(
            method="POST",
            path="/items",
            params=params,
            json=body,
        )

        if response.status_code not in (200, 201):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to create item in Zoho Books",
                    "zoho_response": response.json(),
                },
            )

        data = response.json()
        item = data.get("item", {})

        # Bust all item list cache entries so the new item appears immediately
        cache.delete_pattern("zoho:items:*")

        return {
            "message": "Item created successfully",
            "item": item,
        }

    # -----------------------------
    # Get Item Image (Proxy)
    # -----------------------------
    def get_item_image(self, item_id: str):
        """Proxy Zoho item image so the frontend doesn't need Zoho auth."""
        params = {"organization_id": config.ZOHO_ORG_ID}

        resp = zoho_request(
            method="GET",
            path=f"/items/{item_id}/image",
            params=params,
        )

        if resp.status_code != 200:
            raise HTTPException(
                status_code=resp.status_code,
                detail={
                    "message": "Failed to fetch image from Zoho",
                    "zoho_response": resp.json(),
                },
            )

        return Response(content=resp.content, media_type="image/jpeg")

    # -----------------------------
    # Get Taxes (CACHED)
    # -----------------------------
    def get_taxes(self):
        cache_key = "zoho:taxes"

        cached = cache.get(cache_key)
        if cached:
            return cached

        params = {"organization_id": config.ZOHO_ORG_ID}

        response = zoho_request(method="GET", path="/settings/taxes", params=params)

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to fetch taxes from Zoho Books",
                    "zoho_response": response.json(),
                },
            )

        data = response.json()
        cache.set(cache_key, data)

        return data
