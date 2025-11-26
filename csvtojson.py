import pandas as pd
import json

# File paths
excel_file_path = 'input.xlsx'   # Replace with your Excel file path
json_file_path = 'output.json'   # Desired JSON output path

# Read Excel file
df = pd.read_excel(excel_file_path)

# Convert to custom JSON format
data = []
for _, row in df.iterrows():
    data.append({
        "erp_external_id": str(row["citydetailid"]),
        "name": row["citynames"],
        "statename": row["statename"]
    })

# Write JSON file
with open(json_file_path, 'w', encoding='utf-8') as json_file:
    json.dump(data, json_file, indent=4)

print(f"Excel data has been converted to JSON and saved to {json_file_path}")
