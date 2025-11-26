import json

# Load your huge subcategories_data list from a file
with open("subcategories_data.json", "r", encoding="utf-8") as f:
    subcategories_data = json.load(f)

# Use a set to remove duplicates
unique_set = set()
unique_list = []

for item in subcategories_data:
    key = (item["name"].strip(), item["category"].strip())

    if key not in unique_set:
        unique_set.add(key)
        unique_list.append({
            "name": item["name"].strip(),
            "category": item["category"].strip()
        })

# Save the cleaned deduplicated output
with open("subcategories_data_clean.json", "w", encoding="utf-8") as f:
    json.dump(unique_list, f, indent=4, ensure_ascii=False)

print("Duplicates removed → subcategories_data_clean.json created.")
