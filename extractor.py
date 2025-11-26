import json

# Load JSON array from file
with open("product.json", "r", encoding="utf-8") as f:
    items = json.load(f)

categories = {}        # unique categories
subcategories = set()  # unique subcategories


for item in items:
    category_name = item.get("category") or item.get("name")
    description = item.get("description", "")

    # Store unique main categories
    if category_name not in categories:
        categories[category_name] = description

    # Store unique subcategories
    if item.get("subcategory"):
        subcategories.add((item["subcategory"], category_name))


# Build final outputs
categories_data = [
    {"name": name, "description": desc}
    for name, desc in categories.items()
]

subcategories_data = [
    {"name": sub, "category": cat}
    for sub, cat in subcategories
]

# Write outputs to two JSON files
with open("categories_data.json", "w", encoding="utf-8") as f:
    json.dump(categories_data, f, indent=4, ensure_ascii=False)

with open("subcategories_data.json", "w", encoding="utf-8") as f:
    json.dump(subcategories_data, f, indent=4, ensure_ascii=False)

print("Created categories_data.json and subcategories_data.json")
